#!/usr/bin/env python3
"""Standalone daemon: switches the RIID system's onboard WiFi between Access
Point and Station mode. Controlled primarily via a local Unix socket (the
GUI's Network Setup card) and secondarily via an MCU-wired jumper cable, as
an advanced/manual fallback.

Runs as root via wifi/systemd/wifi-mode-switcher.service, independent of
gui/ (meant to run in a Docker container without host network/root
privileges) - vendors its own trimmed `_ArduinoBridge` RPC client rather
than importing gui/mcu_interface.py's.
"""

import json
import logging
import os
import socket
import subprocess
import threading
import time

import msgpack

SOCKET_PATH = "/var/run/arduino-router.sock"
GUI_SOCKET_PATH = "/var/run/riid-wifi.sock"
_WIFI_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_WIFI_DIR, "config", "wifi_config.json")
SWITCH_SCRIPT = os.path.join(_WIFI_DIR, "scripts", "switch_wifi_mode.sh")

POLL_INTERVAL_S = 1.0
# Long enough for the longest transient message ("STA FAILED -> AP MODE") to
# scroll fully across the matrix and stay legible before reverting.
TRANSIENT_TEXT_MS = 20000

WIFI_MODE_AP = 0
WIFI_MODE_STA = 1

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wifi_mode_daemon")


class _ArduinoBridge:
    """Minimal msgpack-rpc client for the Arduino_RouterBridge Unix socket.

    A standalone copy of gui/mcu_interface.py's `_ArduinoBridge`, kept
    separate so this daemon has no dependency on the gui/ package.
    """

    def __init__(self, socket_path=SOCKET_PATH):
        self.socket_path = socket_path
        self.sock = None
        self.msg_counter = 0
        self.pending_responses = {}
        self.running = False
        self.recv_thread = None
        self.lock = threading.Lock()

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        self.running = True
        self.recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.recv_thread.start()

    def call(self, method, *args, timeout=5):
        self.msg_counter += 1
        msgid = self.msg_counter
        packed = msgpack.packb([0, msgid, method, list(args)])

        event = threading.Event()
        with self.lock:
            self.pending_responses[msgid] = {"event": event, "result": None, "error": None}

        self.sock.sendall(packed)

        if event.wait(timeout):
            with self.lock:
                response = self.pending_responses.pop(msgid)
            if response["error"]:
                raise RuntimeError(response["error"])
            return response["result"]

        with self.lock:
            self.pending_responses.pop(msgid, None)
        raise TimeoutError(f"Timeout waiting for {method}")

    def notify(self, method, *args):
        packed = msgpack.packb([2, method, list(args)])
        self.sock.sendall(packed)

    def disconnect(self):
        self.running = False
        if self.sock:
            self.sock.close()
        if self.recv_thread:
            self.recv_thread.join(timeout=1)

    def _receive_loop(self):
        unpacker = msgpack.Unpacker()
        while self.running:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                unpacker.feed(data)
                for msg in unpacker:
                    self._handle_response(msg)
            except OSError:
                break

    def _handle_response(self, msg):
        if not isinstance(msg, list) or len(msg) < 4:
            return
        msg_type, msgid, error, result = msg[0], msg[1], msg[2], msg[3]
        if msg_type != 1:
            return
        with self.lock:
            if msgid in self.pending_responses:
                self.pending_responses[msgid]["error"] = error
                self.pending_responses[msgid]["result"] = result
                self.pending_responses[msgid]["event"].set()


class GuiSocketServer:
    """Local Unix-socket RPC server for the GUI's Network Setup card.

    Same msgpack-rpc framing as the Arduino bridge above. Only channel
    through which the GUI affects WiFi state - it never shells out to
    nmcli/systemctl/sudo itself, only asks this already-root daemon to.
    """

    def __init__(self, daemon, socket_path=GUI_SOCKET_PATH):
        self.daemon = daemon
        self.socket_path = socket_path
        self.methods = {
            "get_state": daemon.handle_get_state,
            "scan_networks": daemon.handle_scan_networks,
            "apply_config": daemon.handle_apply_config,
        }

    def start(self):
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(self.socket_path)
        # World-writable, matching /var/run/arduino-router.sock's own mode -
        # both are local trusted IPC channels reachable by the GUI's
        # (potentially containerized, non-root) user.
        os.chmod(self.socket_path, 0o666)
        server_sock.listen(4)
        logger.info("GUI socket listening at %s", self.socket_path)
        threading.Thread(target=self._accept_loop, args=(server_sock,), daemon=True).start()

    def _accept_loop(self, server_sock):
        while True:
            conn, _ = server_sock.accept()
            threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def _handle_connection(self, conn):
        unpacker = msgpack.Unpacker(raw=False)
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                unpacker.feed(data)
                for msg in unpacker:
                    self._handle_message(conn, msg)
        except OSError:
            pass
        finally:
            conn.close()

    def _handle_message(self, conn, msg):
        if not isinstance(msg, list) or len(msg) < 4 or msg[0] != 0:
            return
        _, msgid, method, args = msg
        handler = self.methods.get(method)
        try:
            if handler is None:
                raise ValueError(f"Unknown method: {method}")
            result = handler(*args)
            error = None
        except Exception as e:
            logger.error("GUI request '%s' failed: %s", method, e)
            result = None
            error = str(e)
        conn.sendall(msgpack.packb([1, msgid, error, result]))


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    config.setdefault("mode", "ap")
    config.setdefault("ap_ssid", "IAEA_RIID_SYSXX")
    config.setdefault("ap_psk", "RIID_IAEA")
    config.setdefault("sta_ssid", "")
    config.setdefault("sta_psk", "")
    config.setdefault("known_networks", [])
    config.setdefault("max_sta_retries", 3)
    return config


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def run_switch_script(mode, ssid, psk=None):
    args = [SWITCH_SCRIPT, mode, ssid]
    if psk is not None:
        args.append(psk)
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("switch_wifi_mode.sh failed: %s", result.stderr.strip())
    return result.returncode == 0


class WifiModeDaemon:
    def __init__(self):
        self.config = load_config()
        self.bridge = _ArduinoBridge()
        self.mode = WIFI_MODE_AP
        self.lock = threading.Lock()
        self.last_switch_ok = True
        self.last_switch_fell_back = False

    def connect_bridge(self):
        while True:
            try:
                self.bridge.connect()
                logger.info("Connected to Arduino RPC bridge at %s", SOCKET_PATH)
                return
            except OSError as e:
                logger.warning("Arduino RPC bridge not reachable yet (%s); retrying in 5s", e)
                time.sleep(5)

    def push_led(self, mode):
        try:
            self.bridge.notify("update_wifi_led", mode)
        except OSError as e:
            logger.warning("Could not update WiFi LED: %s", e)

    def push_transient_text(self, text):
        try:
            self.bridge.notify("show_transient_text", text, TRANSIENT_TEXT_MS)
        except OSError as e:
            logger.warning("Could not update LED matrix: %s", e)

    def switch_to_ap(self, announce=True):
        logger.info("Switching to Access Point mode (%s)", self.config["ap_ssid"])
        ok = run_switch_script("ap", self.config["ap_ssid"], self.config["ap_psk"])
        self.mode = WIFI_MODE_AP
        self.push_led(WIFI_MODE_AP)
        if announce:
            self.push_transient_text("AP MODE")
        return ok

    def switch_to_station(self, announce=True):
        ssid = self.config["sta_ssid"]
        psk = self.config["sta_psk"]
        if not ssid:
            logger.warning("No Station network selected in wifi_config.json; staying in AP mode.")
            self.switch_to_ap()
            return False

        max_retries = self.config["max_sta_retries"]
        for attempt in range(1, max_retries + 1):
            logger.info("Attempting Station connection to '%s' (%d/%d)", ssid, attempt, max_retries)
            if run_switch_script("sta", ssid, psk):
                self.mode = WIFI_MODE_STA
                self.push_led(WIFI_MODE_STA)
                if announce:
                    self.push_transient_text(f"STA MODE: {ssid}")
                return True

        logger.warning("Station connection failed after %d attempts; falling back to AP mode.", max_retries)
        self.switch_to_ap(announce=False)
        self.push_transient_text("STA FAILED -> AP MODE")
        return False

    def toggle(self):
        """Advanced/manual path: flips mode on a jumper-cable hold, reported
        by the MCU via `poll_wifi_button`."""
        with self.lock:
            if self.mode == WIFI_MODE_STA:
                ok = self.switch_to_ap()
                fell_back = False
            else:
                ok = self.switch_to_station()
                fell_back = not ok
            self.last_switch_ok = ok
            self.last_switch_fell_back = fell_back

    def sync_boot_state(self):
        """Applies the mode configured in wifi_config.json (default AP) at startup."""
        if self.config.get("mode", "ap") == "sta":
            self.switch_to_station(announce=False)
        else:
            self.switch_to_ap(announce=False)

    def handle_get_state(self):
        with self.lock:
            return {
                "mode": "sta" if self.mode == WIFI_MODE_STA else "ap",
                "ap_ssid": self.config["ap_ssid"],
                "ap_psk": self.config["ap_psk"],
                "known_networks": self.config["known_networks"],
                "active_sta_ssid": self.config["sta_ssid"],
                "last_switch_ok": self.last_switch_ok,
                "last_switch_fell_back": self.last_switch_fell_back,
            }

    def handle_scan_networks(self):
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SECURITY", "dev", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, check=True, timeout=20,
        )
        seen = set()
        networks = []
        for line in result.stdout.splitlines():
            # nmcli -t escapes literal colons within a field as "\:"; SSID is
            # the first field, SECURITY (possibly containing "\:") the rest.
            ssid, sep, security = line.partition(":")
            security = security.replace("\\:", ":")
            if not sep or not ssid or ssid in seen:
                continue
            seen.add(ssid)
            networks.append({"ssid": ssid, "secured": security not in ("", "--")})
        return networks

    def handle_apply_config(self, mode, ap_ssid, ap_psk, known_networks, active_sta_ssid):
        with self.lock:
            active = next((n for n in known_networks if n["ssid"] == active_sta_ssid), None)
            self.config["mode"] = mode
            self.config["ap_ssid"] = ap_ssid
            self.config["ap_psk"] = ap_psk
            self.config["known_networks"] = known_networks
            self.config["sta_ssid"] = active["ssid"] if active else ""
            self.config["sta_psk"] = active["psk"] if active else ""
            save_config(self.config)

            if mode == "sta":
                ok = self.switch_to_station()
                fell_back = not ok
            else:
                ok = self.switch_to_ap()
                fell_back = False
            self.last_switch_ok = ok
            self.last_switch_fell_back = fell_back
            return {"ok": ok, "fell_back": fell_back}

    def run(self):
        self.connect_bridge()
        with self.lock:
            self.sync_boot_state()

        GuiSocketServer(self).start()

        logger.info("wifi_mode_daemon started; polling jumper state every %.1fs", POLL_INTERVAL_S)
        while True:
            try:
                if self.bridge.call("poll_wifi_button"):
                    self.toggle()
            except (TimeoutError, OSError) as e:
                logger.warning("Jumper poll failed: %s", e)
            time.sleep(POLL_INTERVAL_S)


def main():
    WifiModeDaemon().run()


if __name__ == "__main__":
    main()
