"""The Network Setup card, in the Hardware & Calibration tab: AP/Station
mode selection, Access Point SSID/passphrase, and known Station networks.

:class:`NetworkSetupPanel` is a thin UI layer over `wifi_interface.WifiInterface`
- the WiFi daemon (`wifi/wifi_mode_daemon.py`) is the actual source of truth
and does all the privileged NetworkManager work; this panel only sends it
requests and mirrors its state, plus keeps a local cache
(`gui/data/conf/wifi.json`) so the card still shows something sensible if the
daemon isn't reachable (e.g. not provisioned yet during development).
"""

import asyncio
import json
import os

from nicegui import ui

from config import BRAND_COLORS, WIFI_DB_PATH, WIFI_DEFAULTS, logger

AP_SSID_MAX_LEN = 24
WPA2_PSK_MIN_LEN = 8
WPA2_PSK_MAX_LEN = 63


class NetworkSetupPanel:
    """Editable WiFi AP/Station settings, applied through the WiFi daemon."""

    def __init__(self, system, wifi_interface):
        """Builds the panel's widgets.

        Args:
            system (SpectrumAcquisitionSystem): Source of the current
                SYS-ID, always appended as a suffix to the AP SSID.
            wifi_interface (wifi_interface.WifiInterface): Client for the
                WiFi daemon's local socket.
        """
        self.system = system
        self.wifi_interface = wifi_interface

        state = self.wifi_interface.get_state()
        if state is not None:
            self.mode = state["mode"]
            self.ap_ssid_custom = self._strip_sys_id_suffix(state["ap_ssid"])
            self.ap_psk = state["ap_psk"]
            self.known_networks = list(state["known_networks"])
            self.active_sta_ssid = state["active_sta_ssid"]
        else:
            cache = self._load_cache()
            self.mode = cache["mode"]
            self.ap_ssid_custom = cache["ap_ssid_custom"]
            self.ap_psk = cache["ap_psk"]
            self.known_networks = list(cache["known_networks"])
            self.active_sta_ssid = cache["active_sta_ssid"]

        self.render_layout()

    # --- Local cache (gui/data/conf/wifi.json) ---------------------------

    def _load_cache(self) -> dict:
        if os.path.exists(WIFI_DB_PATH):
            try:
                with open(WIFI_DB_PATH, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                return {**WIFI_DEFAULTS, **cached}
            except Exception as e:
                logger.error("Error reading WiFi cache %s: %s", WIFI_DB_PATH, e)
        return dict(WIFI_DEFAULTS)

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(WIFI_DB_PATH), exist_ok=True)
            with open(WIFI_DB_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "mode": self.mode,
                    "ap_ssid_custom": self.ap_ssid_custom,
                    "ap_psk": self.ap_psk,
                    "known_networks": self.known_networks,
                    "active_sta_ssid": self.active_sta_ssid,
                }, f, indent=2)
        except Exception as e:
            logger.error("Failed to write WiFi cache %s: %s", WIFI_DB_PATH, e)

    # --- AP SSID composition ----------------------------------------------

    def _current_sys_id(self) -> str:
        return self.system.hw_profile.get("SYS-ID", "SYS-STANDBY")

    def _strip_sys_id_suffix(self, full_ssid: str) -> str:
        """Best-effort recovery of the customizable part from a full SSID
        (e.g. loading state the daemon already has) - falls back to the
        whole string if it doesn't end with the current SYS-ID."""
        suffix = f"_{self._current_sys_id()}"
        if full_ssid.endswith(suffix):
            return full_ssid[: -len(suffix)]
        return full_ssid

    def _composed_ap_ssid(self, custom: str) -> str:
        """Composes the full AP SSID: the user-editable name plus a mandatory
        SYS-ID suffix. The SYS-ID always survives intact - if the combined
        length would exceed the 32-byte 802.11 SSID limit, the customizable
        part is shortened further (below its normal 24-char cap), never the
        suffix."""
        sys_id = self._current_sys_id()
        custom = (custom or WIFI_DEFAULTS["ap_ssid_custom"]).strip()[:AP_SSID_MAX_LEN]
        max_custom_len = max(0, 32 - 1 - len(sys_id))
        custom = custom[:max_custom_len]
        return f"{custom}_{sys_id}" if custom else sys_id

    # --- Layout -------------------------------------------------------------

    def render_layout(self):
        with ui.card().classes('w-full h-full p-4 rounded-lg border shadow-md bg-white space-y-3'):
            ui.label('Network Setup').classes('text-xs font-bold uppercase tracking-wider text-zinc-700 border-b pb-1 w-full')

            # Radio (not a toggle) makes "exactly one mode active" explicit,
            # and pairs with only showing that mode's settings below.
            ui.label('Select WiFi Mode').classes('text-sm font-bold text-zinc-800')
            self.mode_radio = ui.radio(
                {'ap': 'Access Point (AP)', 'sta': 'Station (STA)'}, value=self.mode
            ).props('inline').classes('w-full')

            with ui.column().classes('w-full gap-2') as self.ap_group:
                ui.label('Access Point settings').classes('text-xs font-bold').style(f"color: {BRAND_COLORS['primary']};")
                self.ap_name_input = ui.input(
                    'Access Point name', value=self.ap_ssid_custom, placeholder=WIFI_DEFAULTS['ap_ssid_custom'],
                ).props(f'dense outlined maxlength={AP_SSID_MAX_LEN} counter').classes('w-full text-xs')
                self.ap_ssid_preview = ui.label().classes('text-[11px] font-mono text-zinc-500')
                self.ap_psk_input = ui.input(
                    'Access Point passphrase', value=self.ap_psk, password=True, password_toggle_button=True,
                ).props('dense outlined').classes('w-full text-xs')
                self.ap_name_input.on_value_change(lambda e: self._refresh_ap_preview())
                self._refresh_ap_preview()

            with ui.column().classes('w-full gap-2') as self.sta_group:
                ui.label('Known Station networks').classes('text-xs font-bold').style(f"color: {BRAND_COLORS['primary']};")
                self.networks_container = ui.column().classes('w-full gap-1')
                with ui.row().classes('w-full gap-2 items-center'):
                    self.new_ssid_input = ui.input('SSID').props('dense outlined').classes('flex-1 text-xs')
                    self.new_psk_input = ui.input('Passphrase (blank = open)', password=True, password_toggle_button=True).props('dense outlined').classes('flex-1 text-xs')
                    ui.button(icon='add', on_click=self.add_network).props('dense round outline')
                ui.button('Scan for networks', icon='wifi_find', on_click=self.do_scan).props('dense outline').classes('text-xs')
                self.scan_results_select = ui.select(options=[], label='Scanned networks - pick to prefill above').props('dense outlined').classes('w-full text-xs')
                self.scan_results_select.on_value_change(lambda e: self._prefill_from_scan(e.value))
                self.scan_results_select.set_visibility(False)

                ui.label('Connect to (Station mode):').classes('text-xs font-bold mt-2').style(f"color: {BRAND_COLORS['primary']};")
                self.active_network_select = ui.select(options=[]).props('dense outlined').classes('w-full text-xs')
                self.active_network_select.on_value_change(self._set_active_network)

            self.mode_radio.on_value_change(lambda e: self._apply_mode_visibility())
            self._apply_mode_visibility()
            self._refresh_networks_list()

            with ui.row().classes('w-full mt-1 justify-end'):
                ui.button('APPLY NETWORK CHANGES', icon='wifi_tethering', on_click=self.open_warning_dialog) \
                    .style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;") \
                    .classes('py-2 px-4 text-xs shadow-md rounded-md')

        self._build_dialogs()

    def refresh_sys_id_preview(self):
        """Called every UI sync tick - the composed SSID preview must track
        SYS-ID changes (e.g. a different DAQ board hot-plugged in) even
        though the operator hasn't touched this card."""
        self._refresh_ap_preview()

    def _refresh_ap_preview(self):
        full = self._composed_ap_ssid(self.ap_name_input.value)
        self.ap_ssid_preview.set_text(f"Full Access Point SSID: {full}")

    def _apply_mode_visibility(self):
        """Shows only the selected mode's settings section."""
        is_ap = self.mode_radio.value == 'ap'
        self.ap_group.set_visibility(is_ap)
        self.sta_group.set_visibility(not is_ap)

    # --- Known networks list -------------------------------------------------

    def _refresh_networks_list(self):
        self.networks_container.clear()
        with self.networks_container:
            if not self.known_networks:
                ui.label('No known networks yet.').classes('text-xs text-zinc-400 italic')
            for net in self.known_networks:
                with ui.row().classes('w-full items-center gap-2 text-xs'):
                    icon = 'lock' if net['psk'] else 'lock_open'
                    ui.icon(icon).classes('text-zinc-400')
                    ui.label(net['ssid']).classes('flex-1 font-mono')
                    ui.button(icon='delete', on_click=lambda e, ssid=net['ssid']: self.delete_network(ssid)) \
                        .props('dense flat round').classes('text-red-600')

        options = [n['ssid'] for n in self.known_networks]
        self.active_network_select.options = options
        if self.active_sta_ssid not in options:
            self.active_sta_ssid = options[0] if options else ""
        self.active_network_select.set_value(self.active_sta_ssid or None)
        self.active_network_select.update()

    def add_network(self):
        ssid = (self.new_ssid_input.value or '').strip()
        psk = self.new_psk_input.value or ''
        if not ssid:
            ui.notify("Enter an SSID first.", type="negative")
            return
        if psk and not (WPA2_PSK_MIN_LEN <= len(psk) <= WPA2_PSK_MAX_LEN):
            ui.notify(f"Passphrase must be {WPA2_PSK_MIN_LEN}-{WPA2_PSK_MAX_LEN} characters, or blank for an open network.", type="negative")
            return

        self.known_networks = [n for n in self.known_networks if n['ssid'] != ssid]
        self.known_networks.append({"ssid": ssid, "psk": psk})
        self.active_sta_ssid = ssid
        self.new_ssid_input.set_value('')
        self.new_psk_input.set_value('')
        self._refresh_networks_list()

    def delete_network(self, ssid):
        self.known_networks = [n for n in self.known_networks if n['ssid'] != ssid]
        if self.active_sta_ssid == ssid:
            self.active_sta_ssid = ""
        self._refresh_networks_list()

    def _set_active_network(self, e):
        self.active_sta_ssid = e.value or ""

    async def do_scan(self):
        # Checked live (not self.mode, which only reflects state as of page
        # load) - scanning while actually in AP mode disconnects anyone
        # connected through this system's own AP, likely including this GUI
        # session itself.
        state = await asyncio.to_thread(self.wifi_interface.get_state)
        if state is not None and state["mode"] == "ap":
            ui.notify(
                "Cannot scan while in Access Point mode - it would disconnect anyone connected through this system's AP.",
                type="negative",
            )
            return

        ui.notify("Scanning for nearby networks...", type="info")
        results = await asyncio.to_thread(self.wifi_interface.scan_networks)
        if results is None:
            ui.notify("Could not reach the WiFi daemon to scan - is it running?", type="negative")
            return
        if not results:
            ui.notify("No networks found.", type="warning")
            return
        self._scan_results = {r['ssid']: r['secured'] for r in results}
        self.scan_results_select.options = [
            f"{ssid} ({'secured' if secured else 'open'})" for ssid, secured in self._scan_results.items()
        ]
        self.scan_results_select.set_visibility(True)
        self.scan_results_select.update()

    def _prefill_from_scan(self, label):
        if not label:
            return
        ssid = label.rsplit(' (', 1)[0]
        self.new_ssid_input.set_value(ssid)
        self.new_psk_input.set_value('')

    # --- Apply flow: warning -> confirmation -> apply -------------------------

    def _build_dialogs(self):
        with ui.dialog() as self.warning_dialog, ui.card().classes('p-4 w-[90vw] max-w-96 space-y-3'):
            ui.label('Change network settings?').classes('text-sm font-bold').style(f"color: {BRAND_COLORS['crimson_trace']};")
            ui.label(
                "Changing WiFi settings will reconfigure this system's network "
                "connection. Any browser session connected to the RIID system "
                "over WiFi is likely to be disconnected. Continue only if you "
                "understand the consequences."
            ).classes('text-xs text-zinc-700')
            with ui.row().classes('w-full gap-2 pt-1'):
                ui.button('Cancel', on_click=self.warning_dialog.close).props('dense outline').classes('flex-1')
                ui.button('Continue', on_click=self.open_confirm_dialog) \
                    .style(f"background-color: {BRAND_COLORS['crimson_trace']} !important; color: #FFFFFF !important; font-weight: bold;") \
                    .props('dense').classes('flex-1')

        with ui.dialog() as self.confirm_dialog, ui.card().classes('p-4 w-[90vw] max-w-96 space-y-3'):
            ui.label('Confirm new network settings').classes('text-sm font-bold').style(f"color: {BRAND_COLORS['crimson_trace']};")
            self.confirm_summary = ui.label('').classes('text-xs text-zinc-700 font-mono whitespace-pre-line')
            ui.label("The connection to this RIID system is very likely to be lost.").classes('text-xs font-bold text-red-600')
            with ui.row().classes('w-full gap-2 pt-1'):
                ui.button('Cancel', on_click=self.confirm_dialog.close).props('dense outline').classes('flex-1')
                confirm_btn = ui.button('Apply', icon='wifi_tethering', on_click=self.do_apply)
                confirm_btn.style(f"background-color: {BRAND_COLORS['crimson_trace']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('flex-1')

    def open_warning_dialog(self):
        if self.mode_radio.value == 'sta' and not self.active_sta_ssid:
            ui.notify("Select (or add) a Station network first.", type="negative")
            return
        ap_psk = self.ap_psk_input.value or ''
        if not (WPA2_PSK_MIN_LEN <= len(ap_psk) <= WPA2_PSK_MAX_LEN):
            ui.notify(f"Access Point passphrase must be {WPA2_PSK_MIN_LEN}-{WPA2_PSK_MAX_LEN} characters.", type="negative")
            return
        self.warning_dialog.open()

    async def open_confirm_dialog(self):
        self.warning_dialog.close()
        # Yield briefly - closing one dialog and opening another in the same
        # tick can race Quasar's transition and drop the second open().
        await asyncio.sleep(0.1)
        mode = self.mode_radio.value
        if mode == 'ap':
            full_ap_ssid = self._composed_ap_ssid(self.ap_name_input.value)
            psk = self.ap_psk_input.value or ''
            summary = f"Mode: Access Point\nSSID: {full_ap_ssid}\nPassword: {psk}"
        else:
            net = next((n for n in self.known_networks if n['ssid'] == self.active_sta_ssid), None)
            psk = (net['psk'] if net else '') or '(open network)'
            summary = f"Mode: Station\nConnect to: {self.active_sta_ssid}\nPassword: {psk}"
        self.confirm_summary.set_text(summary)
        self.confirm_dialog.open()

    async def do_apply(self):
        mode = self.mode_radio.value
        self.mode = mode
        self.ap_ssid_custom = (self.ap_name_input.value or '').strip()[:AP_SSID_MAX_LEN]
        self.ap_psk = self.ap_psk_input.value or ''
        full_ap_ssid = self._composed_ap_ssid(self.ap_ssid_custom)

        self.confirm_dialog.close()
        ui.notify("Applying network configuration...", type="info")

        result = await asyncio.to_thread(
            self.wifi_interface.apply_config,
            mode, full_ap_ssid, self.ap_psk, self.known_networks, self.active_sta_ssid,
        )
        self._save_cache()

        if result is None:
            ui.notify("Could not reach the WiFi daemon - settings were saved locally but not applied.", type="negative")
        elif result.get("fell_back"):
            ui.notify("Station connection failed - fell back to Access Point mode.", type="warning")
        elif result.get("ok"):
            ui.notify("Network configuration applied.", type="positive")
        else:
            ui.notify("Applying the network configuration failed - check the WiFi daemon logs.", type="negative")
