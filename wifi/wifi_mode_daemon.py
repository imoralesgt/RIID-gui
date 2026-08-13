#!/usr/bin/env python3
"""Standalone daemon: polls the RIID system's externally-wired WiFi-mode
push-button over the Arduino RPC bridge and toggles the host's WiFi between
Access Point and Station mode via NetworkManager.

Runs directly on the host as root via wifi/systemd/wifi-mode-switcher.service,
independent of gui/ (which runs in a Docker container without host network
privileges). Vendors its own trimmed copy of gui/mcu_interface.py's
`_ArduinoBridge` RPC client rather than importing it, so it has no dependency
on the gui/ package.

The MCU sketch (mcu/app/riid_viz/riid_viz.ino) tracks the button-hold
duration itself and exposes a simple "toggle requested" latch via the
`poll_wifi_button` RPC method; this daemon only polls that latch once a
second and reacts to it.
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
_WIFI_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_WIFI_DIR, "config", "wifi_config.json")
SWITCH_SCRIPT = os.path.join(_WIFI_DIR, "scripts", "switch_wifi_mode.sh")

POLL_INTERVAL_S = 1.0
# Long enough for the longest transient message ("STA FAILED -> AP MODE") to
# scroll fully across the matrix and stay legible before reverting.
TRANSIENT_TEXT_MS = 20000
AP_SSID_PREFIX = "IAEA_RIID_"

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


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    config.setdefault("max_sta_retries", 3)
    config.setdefault("ap_psk", "RIID_IAEA")
    return config


def active_connection_id():
    """Returns whichever of 'riid-ap'/'riid-sta' NetworkManager currently
    reports as active, or None if neither is."""
    result = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
        capture_output=True, text=True, check=True,
    )
    active_names = result.stdout.splitlines()
    for name in ("riid-ap", "riid-sta"):
        if name in active_names:
            return name
    return None


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
        self.mode = WIFI_MODE_STA

    def connect_bridge(self):
        while True:
            try:
                self.bridge.connect()
                logger.info("Connected to Arduino RPC bridge at %s", SOCKET_PATH)
                return
            except OSError as e:
                logger.warning("Arduino RPC bridge not reachable yet (%s); retrying in 5s", e)
                time.sleep(5)

    def ap_ssid(self):
        return f"{AP_SSID_PREFIX}{self.config['sys_id']}"

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
        logger.info("Switching to Access Point mode (%s)", self.ap_ssid())
        run_switch_script("ap", self.ap_ssid(), self.config["ap_psk"])
        self.mode = WIFI_MODE_AP
        self.push_led(WIFI_MODE_AP)
        if announce:
            self.push_transient_text("AP MODE")

    def switch_to_station(self, announce=True):
        ssid = self.config["sta_ssid"]
        psk = self.config["sta_psk"]
        if not ssid:
            logger.warning("No Station SSID configured in wifi_config.json; staying in AP mode.")
            self.switch_to_ap()
            return

        max_retries = self.config["max_sta_retries"]
        for attempt in range(1, max_retries + 1):
            logger.info("Attempting Station connection to '%s' (%d/%d)", ssid, attempt, max_retries)
            if run_switch_script("sta", ssid, psk):
                self.mode = WIFI_MODE_STA
                self.push_led(WIFI_MODE_STA)
                if announce:
                    self.push_transient_text(f"STA MODE: {ssid}")
                return

        logger.warning("Station connection failed after %d attempts; falling back to AP mode.", max_retries)
        self.switch_to_ap(announce=False)
        self.push_transient_text("STA FAILED -> AP MODE")

    def toggle(self):
        if self.mode == WIFI_MODE_STA:
            self.switch_to_ap()
        else:
            self.switch_to_station()

    def sync_boot_state(self):
        """Boots into Station mode by default; only stays in AP mode if it's
        already the NetworkManager-active connection from a prior run."""
        active = active_connection_id()
        if active == "riid-ap":
            self.mode = WIFI_MODE_AP
            self.push_led(WIFI_MODE_AP)
        else:
            self.switch_to_station(announce=False)

    def run(self):
        self.connect_bridge()
        self.sync_boot_state()

        logger.info("wifi_mode_daemon started; polling button state every %.1fs", POLL_INTERVAL_S)
        while True:
            try:
                if self.bridge.call("poll_wifi_button"):
                    self.toggle()
            except (TimeoutError, OSError) as e:
                logger.warning("Button poll failed: %s", e)
            time.sleep(POLL_INTERVAL_S)


def main():
    WifiModeDaemon().run()


if __name__ == "__main__":
    main()
