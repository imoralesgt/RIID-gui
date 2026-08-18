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

# Slower than POLL_INTERVAL_S (which is tuned for jumper-button UX) so a
# transient WiFi blip - AP reboot, DHCP renewal - doesn't trip a fallback.
STA_CHECK_INTERVAL_S = 5.0
STA_MAX_FAILURES = 10

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
        """Connects to the Arduino RPC socket and starts the background receive thread."""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        self.running = True
        self.recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.recv_thread.start()

    def call(self, method, *args, timeout=5):
        """Sends an RPC request and blocks for its response.

        Args:
            method (str): Name of the Arduino-side method to invoke.
            *args: Positional arguments forwarded to that method.
            timeout (float): Seconds to wait for a response.

        Returns:
            The method's return value, as decoded from the response.

        Raises:
            RuntimeError: If the Arduino side reported an error.
            TimeoutError: If no response arrives within `timeout`.
        """
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
        """Sends a fire-and-forget RPC notification (no response expected).

        Args:
            method (str): Name of the Arduino-side method to invoke.
            *args: Positional arguments forwarded to that method.
        """
        packed = msgpack.packb([2, method, list(args)])
        self.sock.sendall(packed)

    def disconnect(self):
        """Closes the socket and stops the background receive thread."""
        self.running = False
        if self.sock:
            self.sock.close()
        if self.recv_thread:
            self.recv_thread.join(timeout=1)

    def _receive_loop(self):
        """Background thread: decodes incoming messages and dispatches responses."""
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
        """Resolves the pending `call()` matching a decoded response message.

        Args:
            msg (list): A decoded msgpack-rpc frame.
        """
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
        """Binds the socket and starts the background accept-loop thread."""
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
        """Background thread: accepts connections, one handler thread each.

        Args:
            server_sock (socket.socket): The listening server socket.
        """
        while True:
            conn, _ = server_sock.accept()
            threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def _handle_connection(self, conn):
        """Reads and dispatches messages from one client connection until it closes.

        Args:
            conn (socket.socket): The accepted client connection.
        """
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
        """Dispatches one decoded request to its handler and replies with the result.

        Args:
            conn (socket.socket): The client connection to reply on.
            msg (list): A decoded msgpack-rpc request frame.
        """
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
    """Reads wifi_config.json, filling in any missing keys with defaults.

    Returns:
        dict: The daemon's configuration.
    """
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
    """Persists the configuration dict to wifi_config.json.

    Args:
        config (dict): The daemon's configuration, as returned by `load_config`.
    """
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def run_switch_script(mode, ssid, psk=None):
    """Runs switch_wifi_mode.sh to actually reconfigure NetworkManager.

    Args:
        mode (str): "ap" or "sta".
        ssid (str): SSID to configure.
        psk (str | None): Passphrase, or None for an open Station network.

    Returns:
        bool: True if the script exited successfully.
    """
    args = [SWITCH_SCRIPT, mode, ssid]
    if psk is not None:
        args.append(psk)
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("switch_wifi_mode.sh failed: %s", result.stderr.strip())
    return result.returncode == 0


class WifiModeDaemon:
    """Owns the current WiFi mode/config and drives every mode switch.

    The single source of truth for `wifi_config.json` and the live NetworkManager
    state; both the jumper-cable poll loop (`toggle`) and the GUI socket
    (`handle_*`) go through this class, guarded by `self.lock`.
    """

    def __init__(self):
        self.config = load_config()
        self.bridge = _ArduinoBridge()
        self.mode = WIFI_MODE_AP
        self.lock = threading.Lock()
        self.last_switch_ok = True
        self.last_switch_fell_back = False

    def connect_bridge(self):
        """Blocks until the Arduino RPC bridge socket is reachable, retrying every 5s."""
        while True:
            try:
                self.bridge.connect()
                logger.info("Connected to Arduino RPC bridge at %s", SOCKET_PATH)
                return
            except OSError as e:
                logger.warning("Arduino RPC bridge not reachable yet (%s); retrying in 5s", e)
                time.sleep(5)

    def push_led(self, mode):
        """Updates the board's WiFi-mode LED.

        Args:
            mode (int): `WIFI_MODE_AP` or `WIFI_MODE_STA`.
        """
        try:
            self.bridge.notify("update_wifi_led", mode)
        except OSError as e:
            logger.warning("Could not update WiFi LED: %s", e)

    def push_transient_text(self, text):
        """Scrolls a temporary status message across the LED matrix.

        Args:
            text (str): The message to display.
        """
        try:
            self.bridge.notify("show_transient_text", text, TRANSIENT_TEXT_MS)
        except OSError as e:
            logger.warning("Could not update LED matrix: %s", e)

    def switch_to_ap(self, announce=True):
        """Switches NetworkManager to Access Point mode using the current config.

        Args:
            announce (bool): Whether to scroll a "AP MODE" message on the LED matrix.

        Returns:
            bool: True if the switch script succeeded.
        """
        logger.info("Switching to Access Point mode (%s)", self.config["ap_ssid"])
        ok = run_switch_script("ap", self.config["ap_ssid"], self.config["ap_psk"])
        self.mode = WIFI_MODE_AP
        self.push_led(WIFI_MODE_AP)
        if announce:
            self.push_transient_text("AP MODE")
        return ok

    def switch_to_station(self, announce=True):
        """Switches NetworkManager to Station mode, retrying and falling back to AP on failure.

        Args:
            announce (bool): Whether to scroll a "STA MODE: <ssid>" message on
                success (a fallback failure message always shows regardless).

        Returns:
            bool: True if the Station connection succeeded; False if it fell
                back to Access Point mode.
        """
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

    def is_sta_connected(self) -> bool:
        """Checks whether the riid-sta NetworkManager connection is still active.

        Returns:
            bool: True if riid-sta is currently active, or if the check
                itself failed to run (treated as inconclusive, not a
                connectivity failure, to avoid false fallbacks from
                transient nmcli/tooling errors).
        """
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
                capture_output=True, text=True, check=True, timeout=10,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("Could not check Station connectivity: %s", e)
            return True
        return "riid-sta" in result.stdout.splitlines()

    def sta_watchdog_loop(self):
        """Background thread: while live in Station mode, checks connectivity
        every STA_CHECK_INTERVAL_S and falls back to Access Point mode after
        STA_MAX_FAILURES consecutive failed checks.

        Mirrors `handle_scan_networks`: the mode check and the (up to 10s)
        nmcli call both run unlocked, so a slow check doesn't stall GUI/jumper
        requests for that whole window - only the actual fallback switch is
        guarded by `self.lock`.
        """
        fail_count = 0
        while True:
            time.sleep(STA_CHECK_INTERVAL_S)
            if self.mode != WIFI_MODE_STA:
                fail_count = 0
                continue
            if self.is_sta_connected():
                fail_count = 0
                continue

            fail_count += 1
            logger.warning("Station connectivity check failed (%d/%d)", fail_count, STA_MAX_FAILURES)
            if fail_count >= STA_MAX_FAILURES:
                logger.warning("Station connection lost; falling back to Access Point mode.")
                with self.lock:
                    ok = self.switch_to_ap(announce=False)
                    self.last_switch_ok = ok
                    self.last_switch_fell_back = True
                self.push_transient_text("STA LOST -> AP MODE")
                fail_count = 0

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
        """RPC handler: reports the current WiFi state to the GUI.

        Returns:
            dict: "mode", "ap_ssid", "ap_psk", "known_networks",
                "active_sta_ssid", "last_switch_ok", "last_switch_fell_back".
        """
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
        """RPC handler: scans for nearby WiFi networks.

        Returns:
            list[dict]: De-duplicated {"ssid", "secured"} entries.

        Raises:
            RuntimeError: If currently live in Access Point mode.
        """
        if self.mode == WIFI_MODE_AP:
            # Scanning forces the radio off AP duty momentarily, dropping any
            # client currently connected through it - including, likely,
            # whoever just clicked this from the GUI.
            raise RuntimeError("Cannot scan for networks while in Access Point mode - it would disconnect anyone connected through this system's AP.")
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
        """RPC handler: saves new settings and switches to the requested mode.

        Args:
            mode (str): "ap" or "sta".
            ap_ssid (str): Complete Access Point SSID.
            ap_psk (str): Access Point passphrase.
            known_networks (list[dict]): {"ssid", "psk"} dicts for all saved
                Station networks.
            active_sta_ssid (str): SSID (from `known_networks`) to connect to
                when `mode` is "sta".

        Returns:
            dict: {"ok": bool, "fell_back": bool} describing the outcome.
        """
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
        """Connects the Arduino bridge, applies boot state, and polls the jumper forever."""
        self.connect_bridge()
        with self.lock:
            self.sync_boot_state()

        GuiSocketServer(self).start()
        threading.Thread(target=self.sta_watchdog_loop, daemon=True).start()

        logger.info("wifi_mode_daemon started; polling jumper state every %.1fs", POLL_INTERVAL_S)
        while True:
            try:
                if self.bridge.call("poll_wifi_button"):
                    self.toggle()
            except (TimeoutError, OSError) as e:
                logger.warning("Jumper poll failed: %s", e)
            time.sleep(POLL_INTERVAL_S)


def main():
    """Entry point: builds and runs the daemon."""
    WifiModeDaemon().run()


if __name__ == "__main__":
    main()
