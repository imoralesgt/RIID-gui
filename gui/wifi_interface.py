"""Client for the WiFi daemon's local GUI-facing socket.

wifi/wifi_mode_daemon.py exposes /var/run/riid-wifi.sock using the same
msgpack-rpc framing gui/mcu_interface.py already uses for the Arduino RPC
bridge (`[0, msgid, method, args]` request / `[1, msgid, error, result]`
response). `WifiInterface` is this GUI's thin client for it, used by
view_network.py's Network Setup card - the GUI never touches nmcli,
NetworkManager, or sudo itself, it only asks the already-root daemon to.
"""

import socket

import msgpack

from config import logger, WIFI_SOCKET_PATH


class _WifiBridge:
    """Minimal msgpack-rpc client, one connection per call.

    Unlike the Arduino bridge's `_ArduinoBridge` (a long-lived connection
    with a background receive thread, since the MCU also pushes status polls
    at 1Hz), each WiFi daemon request is a one-off triggered by a UI action -
    a fresh connection per call keeps this client simple and avoids tracking
    a persistent socket's liveness across the unpredictable gaps between
    GUI actions.
    """

    def __init__(self, socket_path=WIFI_SOCKET_PATH):
        self.socket_path = socket_path

    def call(self, method, *args, timeout=5):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
            sock.sendall(msgpack.packb([0, 1, method, list(args)]))

            unpacker = msgpack.Unpacker(raw=False)
            while True:
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("WiFi daemon closed the connection")
                unpacker.feed(data)
                for msg in unpacker:
                    if not isinstance(msg, list) or len(msg) < 4 or msg[0] != 1:
                        continue
                    _, _, error, result = msg
                    if error:
                        raise RuntimeError(error)
                    return result


class WifiInterface:
    """Thin client for the WiFi mode daemon, used by view_network.py.

    Fails soft on any connection problem (daemon not installed/running yet,
    socket not reachable) rather than raising - mirrors `ArduinoInterface`'s
    handling of an unreachable Arduino bridge, since the daemon may not be
    provisioned during development.
    """

    def __init__(self):
        self.bridge = _WifiBridge()

    def get_state(self):
        """Returns the daemon's current WiFi state dict, or None if unreachable."""
        try:
            return self.bridge.call("get_state")
        except (OSError, RuntimeError) as e:
            logger.warning(f"Could not reach WiFi daemon for get_state: {e}")
            return None

    def scan_networks(self):
        """Returns a list of {"ssid", "secured"} dicts, or None if unreachable/failed."""
        try:
            return self.bridge.call("scan_networks", timeout=25)
        except (OSError, RuntimeError) as e:
            logger.warning(f"Could not scan for networks: {e}")
            return None

    def apply_config(self, mode, ap_ssid, ap_psk, known_networks, active_sta_ssid):
        """Pushes new WiFi settings to the daemon and triggers the mode switch.

        Returns a {"ok": bool, "fell_back": bool} dict on success, or None if
        the daemon couldn't be reached at all.
        """
        try:
            return self.bridge.call(
                "apply_config", mode, ap_ssid, ap_psk, known_networks, active_sta_ssid,
                timeout=30,
            )
        except (OSError, RuntimeError) as e:
            logger.warning(f"Could not apply WiFi config: {e}")
            return None
