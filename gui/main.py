"""Application entry point: NiceGUI page shell and top-level app wiring.

Instantiates the shared :class:`~riid_service.RIIDCoreService` backend
singleton, registers the app-startup hardware probe, and builds the four-tab
station UI (:class:`RIIDSpectroscopyApp`) served at the root ``/`` route.
Run directly with ``uv run main.py`` (see the repository README).
"""

from nicegui import app, ui
import asyncio
import os
from config import BRAND_COLORS, logger
from riid_service import RIIDCoreService
from view_spectrum_id import SpectrumPlotContainer, ControlPanelSidebar
from view_recording import SpectrumRecordingPanel
from view_download import SpectraDownloadPanel
from view_calibration import HardwareCalibrationPanel
from view_network import NetworkSetupPanel

# Explicitly serves just this one file at a known URL, rather than relying on
# ui.image()'s implicit "pass it a local path and hope it gets auto-served"
# behavior - which is exactly the kind of path-resolution quirk that made the
# favicon setting silently fail until the leading "./" was dropped. Mounting
# a single named file (not the whole directory via add_static_files) also
# avoids exposing the rest of this directory - source code, config, data -
# over an unauthenticated static route.
#
# Absolute path, anchored to this file's own location (not the ambient
# current working directory the app happens to be launched from) - removes
# any remaining path-resolution ambiguity. Logged loudly if missing, so a
# wrong path fails obviously instead of silently rendering nothing.
_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'iaea_logo.png')
if os.path.isfile(_LOGO_PATH):
    app.add_static_file(local_file=_LOGO_PATH, url_path='/iaea_logo.png')
    logger.info(f"[BOOT] Logo file found and mounted at /iaea_logo.png -> {_LOGO_PATH}")
else:
    logger.error(f"[BOOT] Logo file NOT FOUND at expected path: {_LOGO_PATH} - the header logo will not display.")

# Name of the ML model used for RIID. Available options in folder `ml_models/`
ML_MODEL_NAME = 'cnn_multilabel'

# Instantiate global backend execution singletons
backend_service = RIIDCoreService(ml_model_name = ML_MODEL_NAME)

async def runtime_bootstrap_sequence():
    """App-startup hook: probes for hardware and starts the background service loops."""
    logger.info("[BOOT] Triggering system bootstrap sequence initialization...")
    try:
        await backend_service.initialize_and_probe()
        backend_service.start_service_loops()
        logger.info("[BOOT] Runtime bootstrap sequence finished successfully.")
    except Exception as e:
        logger.error(f"[BOOT] Bootstrap sequence error: {e}", exc_info=True)

app.on_startup(runtime_bootstrap_sequence)

class RIIDSpectroscopyApp:
    """The top-level four-tab station UI, one instance per connected browser client."""

    def __init__(self):
        """Builds the workspace, sets the initial tab title, and starts the UI sync timer."""
        logger.info("[UI_MOUNT] Instantiating client session application station interface...")

        # Explicit tracking initialization variable
        self.current_applied_sys_id = None
        
        # Explicitly define direct widget instance tracking anchors
        self.calibration_panel = None
        self.network_panel = None
        self.plot_view = None
        self.sidebar = None
        self.last_hardware_ok = True
        self.hardware_ok = False
        
        self.build_workspace()
        self.update_browser_tab_title()
        
        # Formally bind the instance sync tick to the active NiceGUI scheduler loop
        ui.timer(1.0, self.global_ui_sync_tick)
        # Separate slower timer, so an unreachable WiFi daemon can't stall the 1s sync tick.
        ui.timer(5.0, self._refresh_wifi_mode_state)
        logger.info("[UI_MOUNT] UI sync timer loop attached at 1.0s interval. Mounting complete.")

    async def _refresh_wifi_mode_state(self):
        """Polls the WiFi daemon's live mode and updates the badge and Network Setup card."""
        state = await asyncio.to_thread(backend_service.wifi_iface.get_state)
        mode = state['mode'] if state else None
        self._set_wifi_mode_badge(mode)
        if self.network_panel is not None:
            self.network_panel.set_live_mode(mode)

    def _set_wifi_mode_badge(self, mode):
        """Updates the header WiFi badge. Colors match LED3 on the board: red for AP, white for STA.

        Args:
            mode (str | None): "ap", "sta", or None if the daemon is unreachable.
        """
        colors = {
            'ap': ('#DC2626', '#DC2626', '#FFFFFF'),
            'sta': ('#FFFFFF', '#D1D5DB', '#1F2937'),
            None: ('#F3F4F6', '#E5E7EB', '#9CA3AF'),
        }
        bg, border, fg = colors.get(mode, colors[None])
        self.wifi_mode_badge.style(f'background-color: {bg}; border-color: {border};')
        self.wifi_mode_icon.style(f'color: {fg};')
        self.wifi_mode_label.style(f'color: {fg};').set_text(mode.upper() if mode else '--')

    def update_browser_tab_title(self):
        """Updates the actual browser tab title text dynamically based on profile records."""
        current_sys_id = backend_service.system.hw_profile.get('SYS-ID', 'SYS-STANDBY')
        self.current_applied_sys_id = current_sys_id
        new_title = f"[{current_sys_id}] - NSIL/IAEA Gamma RIID"
        
        logger.info(f"[UI_TITLE] Re-evaluating client window title properties. Applied Title: {new_title}")
        ui.run_javascript(f"document.title = '{new_title}';")

    def _inject_responsive_styles(self):
        """Mobile-landscape responsive overrides, kept separate from
        build_workspace so that method stays focused on the actual container
        tree rather than growing with embedded CSS.
        
        Gated to a 600px-1024px viewport WIDTH range, not an
        `orientation: landscape` media query - that was tried first, but
        proved unreliable on at least one real device: without a correctly-
        reported viewport, some mobile browsers fall back to treating the
        page as if it were a ~980px-wide desktop page and scale it down,
        which can make `orientation` report inconsistently with the phone's
        actual physical orientation. A width range doesn't have that
        problem: a phone in landscape reliably reports a viewport in the
        ~600-1024px range; the same phone in portrait reliably reports
        ~360-430px, comfortably below this range's floor - so this still
        distinguishes the two cases, just without relying on `orientation`
        at all. The explicit viewport meta tag below is a second, defensive
        measure toward the same end: making sure the browser reports the
        page's true device-width viewport in the first place, rather than a
        virtual one, which matters for any width-based media query here.
        
        Also still gated to max-width:1024px so this never applies on
        desktop monitors (typically 1280px+). The desktop layout (the fixed
        72/28 and 65/35 percentage splits) is completely untouched outside
        this range.
        
        The root problem on a narrow-but-landscape phone: those percentage
        splits leave each side with too few actual pixels once the viewport
        itself is only ~850-930px wide (vs. ~1600px+ on desktop) - the metric
        cards' text wraps to 2-3 lines and the count-rate plot renders
        squished because Plotly is laying out its axes/legend within a
        container barely wide enough for a third of a normal desktop plot.
        Stacking these rows vertically instead gives each section the FULL
        viewport width to render in, rather than a shrinking fraction of one."""
        ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1">')
        ui.add_head_html('''
        <style>
        @media (min-width: 600px) and (max-width: 1024px) {
            .riid-main-split-row, .riid-spectrum-split-row {
                flex-direction: column !important;
            }
            .riid-main-split-row > *, .riid-spectrum-split-row > * {
                width: 100% !important;
                max-width: 100% !important;
            }
            .riid-metric-cards-row {
                flex-wrap: wrap !important;
            }
            .riid-metric-card {
                flex: 1 1 45% !important;
                min-width: 45% !important;
                height: auto !important;
                min-height: 56px !important;
                padding-top: 6px !important;
                padding-bottom: 6px !important;
            }
            .riid-metric-value {
                font-size: 0.95rem !important;
            }
        }
        </style>
        ''')

    def build_workspace(self):
        """Constructs the visual container tree utilizing official palettes."""
        ui.colors(primary=BRAND_COLORS['primary'], secondary=BRAND_COLORS['secondary'])
        self._inject_responsive_styles()
        
        # Outer column spans the full viewport (so the workspace background color
        # still reaches the browser edges), while the inner column caps and
        # centers the actual content - otherwise every control stretches all the
        # way to the window edges on large/maximized displays, which looks
        # sparse and makes rows like the calibration panel unreasonably wide.
        self.workspace_container = ui.column().classes('w-full min-h-screen').style(f"background-color: {BRAND_COLORS['bg_workspace']}; font-family: 'Roboto', sans-serif;")
        with self.workspace_container:
            with ui.column().classes('w-full max-w-[1600px] mx-auto p-3 gap-3'):
                
                # Application Header Layout Block
                with ui.row().classes('w-full justify-between items-center px-2 py-1 border-b').style("border-color: #D1D5DB;"):
                    with ui.row().classes('items-center gap-2'):
                        ui.html('<img src="/iaea_logo.png" style="height: 60px; width: auto; display: block;" alt="IAEA logo" />')
                        ui.markdown("# RIID and spectroscopy station").classes('text-base font-bold text-slate-800 m-0 p-0')
                    
                    # Station ID + connectivity status, stacked into two compact
                    # rows on the right (was: Station ID here, then a separate
                    # full-page-width status stripe below the whole header) - now
                    # both rows together are sized to roughly match the logo's
                    # height. The ONLINE/OFFLINE status text (with its color) is
                    # embedded directly in the Station ID box itself, rather than
                    # being a separate adjacent pill.
                    with ui.column().classes('items-end gap-1'):
                        with ui.row().classes('items-center gap-2 no-wrap'):
                            self.wifi_mode_badge = ui.row().classes('items-center gap-1 px-2 py-1 rounded-full shadow-sm border no-wrap')
                            with self.wifi_mode_badge:
                                self.wifi_mode_icon = ui.icon('wifi', size='xs')
                                self.wifi_mode_label = ui.label('--').classes('text-xs font-mono font-bold')
                            self._set_wifi_mode_badge(None)

                            with ui.row().classes('items-center gap-0 px-3 py-1 rounded bg-white shadow-sm border border-blue-200 no-wrap'):
                                self.station_id_badge = ui.label("Station Node: Syncing...").classes('text-xs font-mono font-bold text-blue-700')
                                ui.label('|').classes('text-xs font-mono text-zinc-300 mx-2')
                                self.banner_status_pill = ui.label("").classes('text-xs font-mono font-bold')
                        
                        # Global Interlock Connectivity Banner View Card - sized to
                        # its own content rather than a fixed max-width, so the
                        # full status message always stays readable instead of
                        # being cropped with an ellipsis.
                        self.connection_alert_banner = ui.row().classes('items-center gap-2 px-3 py-1 rounded-lg border shadow-sm transition-all duration-300')
                        with self.connection_alert_banner:
                            self.banner_icon = ui.icon('report_problem', size='xs')
                            self.banner_text = ui.label("Syncing hardware layers...").classes('text-[11px]')

                # Center Card View Tab selectors layout element frame
                with ui.card().classes('w-full p-0 rounded-lg border shadow-sm no-wrap overflow-hidden').style("background-color: #2D3748; border-color: #1A202C;"):
                    with ui.tabs().classes('w-full dense text-white').on('change', lambda e: logger.info(f"[UI_NAV] Tab shifted to: '{e.value}'")) as self.main_tabs:
                        self.tab_id = ui.tab('Spectrum ID', icon='analytics').classes('text-xs font-bold py-2')
                        self.tab_recording = ui.tab('Spectrum Recording', icon='fiber_manual_record').classes('text-xs font-bold py-2')
                        self.tab_download = ui.tab('Spectra Download', icon='download').classes('text-xs font-bold py-2')
                        self.tab_hardware = ui.tab('Hardware & Calibration', icon='tune').classes('text-xs font-bold py-2')

                # Picks the initial active tab from the backend's CURRENT state,
                # rather than always defaulting to Spectrum ID - otherwise a
                # browser reload while a batch recording is already running
                # would land the operator on a tab that's about to be disabled
                # (Spectrum ID), rather than the one actually in progress.
                if backend_service.is_batch_recording_active:
                    initial_tab = self.tab_recording
                else:
                    initial_tab = self.tab_id
                
                # Dynamic Content Panel Frames Container
                with ui.tab_panels(self.main_tabs, value=initial_tab).classes('w-full bg-transparent p-0 flex-1') as self.tab_panels:
                    with ui.tab_panel(self.tab_id).classes('p-0 m-0 bg-transparent'):
                        with ui.row().classes('w-full gap-3 items-stretch no-wrap riid-main-split-row'):
                            with ui.card().classes('p-4 rounded-lg border shadow-md bg-white gap-3 flex-1').style('width: 72%; border-color: #E2E8F0;'):
                                self.plot_view = SpectrumPlotContainer(backend_service)
                            with ui.card().classes('p-4 rounded-lg border shadow-md bg-white gap-3').style('width: 28%; max-width: 340px; border-color: #E2E8F0;'):
                                self.sidebar = ControlPanelSidebar(backend_service, self.plot_view)

                    with ui.tab_panel(self.tab_recording).classes('p-0 m-0 bg-transparent'):
                        SpectrumRecordingPanel(backend_service)

                    with ui.tab_panel(self.tab_download).classes('p-0 m-0 bg-transparent'):
                        SpectraDownloadPanel(backend_service)

                    with ui.tab_panel(self.tab_hardware).classes('p-0 m-0 bg-transparent'):
                        # Side-by-side on wide screens so Commit stays visually
                        # grouped with calibration, and Network Setup doesn't
                        # push below the fold. Stacks single-column below lg.
                        with ui.row().classes('w-full gap-3 items-stretch flex-col lg:flex-row no-wrap'):
                            with ui.column().classes('w-full lg:w-2/3 gap-0'):
                                self.calibration_panel = HardwareCalibrationPanel(backend_service.system, title_sync_callback=self.update_browser_tab_title, push_profile_callback=backend_service.push_active_profile_to_board)
                            with ui.column().classes('w-full lg:w-1/3 gap-0'):
                                self.network_panel = NetworkSetupPanel(backend_service.system, backend_service.wifi_iface)

    def global_ui_sync_tick(self):
        """Drives all real-time component updates and handles dynamic layout changes."""
        self.last_hardware_ok = self.hardware_ok
        self.hardware_ok = backend_service.is_hardware_available
        current_status = backend_service.status_text
        
        current_sys_id = backend_service.system.hw_profile.get('SYS-ID', 'SYS-STANDBY')
        current_serial = backend_service.system.serial_number
        
        # Logging hardware status updates
        if self.last_hardware_ok != self.hardware_ok:
            logger.info(f"[UI_SYNC_LOOP] available={self.hardware_ok} | serial={current_serial} | msg='{current_status}'")

        # Update node status badge values (with operator guidance modification)
        if current_serial != "UNKNOWN":
            self.station_id_badge.set_text(f"Station: {current_sys_id}")
        else:
            self.station_id_badge.set_text(f"Station: {current_sys_id} (looking for hardware...)")

        # Reactive hot-plug browser tab title adjustment
        if self.current_applied_sys_id != current_sys_id:
            logger.warning(f"[UI_SYNC] Dynamic profile shift detected in title string context ({self.current_applied_sys_id} -> {current_sys_id}). Re-writing window title...")
            self.update_browser_tab_title()

        # Disables the tabs unrelated to whichever session (if any) is
        # currently in progress, to prevent the operator from launching a
        # conflicting run or changing DAQ/calibration settings mid-measurement
        # - either of which could crash the hardware or corrupt the current
        # data. Runs every tick, so this applies both reactively (if a session
        # starts while the operator is on an unrelated tab) and correctly
        # right after a browser reload/reconnect, when a session might already
        # be running in the backend before this client's first tick even
        # fires. If the operator is currently viewing a tab that just became
        # disabled, they're redirected back to whichever tab the active
        # session actually belongs to, rather than being left stranded on
        # (or able to keep interacting with) a now-disabled panel.
        spectrum_id_active = backend_service.is_spectrum_id_active
        batch_active = backend_service.is_batch_recording_active
        
        if spectrum_id_active:
            self.tab_recording.disable()
        else:
            self.tab_recording.enable()
        
        if spectrum_id_active or batch_active:
            self.tab_hardware.disable()
        else:
            self.tab_hardware.enable()
        
        if batch_active:
            self.tab_id.disable()
        else:
            self.tab_id.enable()
        
        current_tab = self.tab_panels.value
        if spectrum_id_active and current_tab in (self.tab_recording, self.tab_hardware):
            logger.warning("[UI_SYNC] Redirected away from a tab disabled by an active Spectrum ID session.")
            self.tab_panels.value = self.tab_id
        elif batch_active and current_tab in (self.tab_id, self.tab_hardware):
            logger.warning("[UI_SYNC] Redirected away from a tab disabled by an active batch recording session.")
            self.tab_panels.value = self.tab_recording

        # Robust direct object validation pattern bypasses container iteration completely
        if self.calibration_panel is not None:
            if self.calibration_panel.last_bound_serial != current_serial:
                logger.info(f"[UI_SYNC] Hardware discovery state transition detected. Forcing configuration fields update...")
                self.calibration_panel.refresh_all_inputs()

        # Keeps the composed AP SSID preview in sync with SYS-ID changes.
        if self.network_panel is not None:
            self.network_panel.refresh_sys_id_preview()

        # Sync subpanel layout charts states
        if self.sidebar is not None and self.plot_view is not None:
            self.sidebar.refresh_widget_states()
            self.plot_view.update_ui_elements()

        # Offline analysis mode takes precedence over the ordinary
        # hardware-connectivity readout - the operator is deliberately not
        # looking at live hardware right now, so "ONLINE"/"DISCONNECTED"
        # would be misleading either way.
        offline_mode = backend_service.offline_mode
        self.workspace_container.style(
            f"background-color: {BRAND_COLORS['bg_workspace_offline' if offline_mode else 'bg_workspace']}; "
            "font-family: 'Roboto', sans-serif;"
        )

        # Handle responsive layout mutations on hot-plug operations
        if offline_mode:
            self.connection_alert_banner.classes(add='bg-red-50 border-red-200 text-red-800', remove='bg-green-50 border-green-200 text-green-800')
            self.banner_icon.set_visibility(False)
            self.banner_text.set_text("Offline analysis mode - reviewing a loaded spectrum, not live hardware.")
            self.banner_status_pill.set_text("Offline analysis").classes(add='text-red-800', remove='text-green-800')
        elif self.hardware_ok:
            self.connection_alert_banner.classes(add='bg-green-50 border-green-200 text-green-800', remove='bg-red-50 border-red-200 text-red-800')
            self.banner_icon.set_visibility(False)
            self.banner_text.set_text(f"Hardware connection online: {current_status}")
            self.banner_status_pill.set_text("ONLINE").classes(add='text-green-800', remove='text-red-800')
        else:
            self.connection_alert_banner.classes(add='bg-red-50 border-red-200 text-red-800', remove='bg-green-50 border-green-200 text-green-800')
            self.banner_icon.set_visibility(True).style("color: #B9222D;")
            self.banner_text.set_text("⚠️ MCA HARDWARE CRITICAL FAILURE: Connection broken or device disconnected. Checking port link auto-discovery loop...")
            self.banner_status_pill.set_text("DISCONNECTED").classes(add='text-red-800', remove='text-green-800')

        # NOTE: DPP parameters are never pushed to the board from this polling tick.
        # They are only transmitted by push_active_profile_to_board(), called
        # explicitly from: (1) initial hardware probe on app/service launch,
        # (2) the operator pressing COMMIT CALIBRATION PARAMETERS, and (3) hardware
        # reconnection recovery in the heartbeat loop.


@ui.page('/')
def index():
    """Serves the station UI at the root route - one fresh app instance per client."""
    RIIDSpectroscopyApp()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="RIID Gamma Spectroscopy Station", port=8080, favicon=_LOGO_PATH, reload=False, show=False)
