from nicegui import app, ui
from config import BRAND_COLORS, logger
from riid_service import RIIDCoreService
from view_spectrum_id import SpectrumPlotContainer, ControlPanelSidebar
from view_recording import SpectrumRecordingPanel
from view_calibration import HardwareCalibrationPanel

# Instantiate global backend execution singletons
backend_service = RIIDCoreService()

async def runtime_bootstrap_sequence():
    logger.info("[BOOT] Triggering system bootstrap sequence initialization...")
    try:
        await backend_service.initialize_and_probe()
        backend_service.start_service_loops()
        logger.info("[BOOT] Runtime bootstrap sequence finished successfully.")
    except Exception as e:
        logger.error(f"[BOOT] Bootstrap sequence error: {e}", exc_info=True)

app.on_startup(runtime_bootstrap_sequence)

class RIIDSpectroscopyApp:
    def __init__(self):
        logger.info("[UI_MOUNT] Instantiating client session application station interface...")
        
        # FIXED: Explicit tracking initialization variable
        self.current_applied_sys_id = None
        
        # Explicitly define direct widget instance tracking anchors
        self.calibration_panel = None
        self.plot_view = None
        self.sidebar = None
        
        self.build_workspace()
        self.update_browser_tab_title()
        
        # Formally bind the instance sync tick to the active NiceGUI scheduler loop
        ui.timer(1.0, self.global_ui_sync_tick)
        logger.info("[UI_MOUNT] UI sync timer loop attached at 1.0s interval. Mounting complete.")

    def update_browser_tab_title(self):
        """Updates the actual browser tab title text dynamically based on profile records."""
        current_sys_id = backend_service.system.hw_profile.get('SYS-ID', 'SYS-STANDBY')
        self.current_applied_sys_id = current_sys_id
        new_title = f"[{current_sys_id}] - NSIL/IAEA Gamma RIID"
        
        logger.info(f"[UI_TITLE] Re-evaluating client window title properties. Applied Title: {new_title}")
        ui.run_javascript(f"document.title = '{new_title}';")

    def build_workspace(self):
        """Constructs the visual container tree utilizing official palettes."""
        ui.colors(primary=BRAND_COLORS['primary'], secondary=BRAND_COLORS['secondary'])
        
        with ui.column().classes('w-full p-3 min-h-screen gap-3').style(f"background-color: {BRAND_COLORS['bg_workspace']}; font-family: 'Roboto', sans-serif;"):
            
            # Application Header Layout Block
            with ui.row().classes('w-full justify-between items-center px-2 py-1 border-b').style("border-color: #D1D5DB;"):
                ui.markdown(f"### **IAEA** RIID Laboratory Spectroscopy Station").classes('text-base font-bold text-slate-800 m-0 p-0')
                self.station_id_badge = ui.label("Station Node: Syncing...").classes('text-xs font-mono font-bold px-3 py-1 rounded bg-white shadow-sm border text-blue-700 border-blue-200')

            # Global Interlock Connectivity Banner View Card
            self.connection_alert_banner = ui.row().classes('w-full items-center justify-between px-4 py-2.5 rounded-lg border shadow-sm transition-all duration-300')
            with self.connection_alert_banner:
                with ui.row().classes('items-center gap-2'):
                    self.banner_icon = ui.icon('report_problem', size='sm')
                    self.banner_text = ui.label("Syncing hardware layers...")
                self.banner_status_pill = ui.label("").classes('text-[10px] font-mono font-bold px-2 py-0.5 rounded')

            # Center Card View Tab selectors layout element frame
            with ui.card().classes('w-full p-0 rounded-lg border shadow-sm no-wrap overflow-hidden').style("background-color: #2D3748; border-color: #1A202C;"):
                with ui.tabs().classes('w-full dense text-white').on('change', lambda e: logger.info(f"[UI_NAV] Tab shifted to: '{e.value}'")) as self.main_tabs:
                    self.tab_id = ui.tab('Spectrum ID', icon='analytics').classes('text-xs font-bold py-2')
                    self.tab_recording = ui.tab('Spectrum Recording', icon='save_alt').classes('text-xs font-bold py-2')
                    self.tab_hardware = ui.tab('Hardware & Calibration', icon='tune').classes('text-xs font-bold py-2')

            # Dynamic Content Panel Frames Container
            with ui.tab_panels(self.main_tabs, value=self.tab_id).classes('w-full bg-transparent p-0 flex-1'):
                with ui.tab_panel(self.tab_id).classes('p-0 m-0 bg-transparent'):
                    with ui.row().classes('w-full gap-3 items-stretch no-wrap'):
                        with ui.card().classes('p-4 rounded-lg border shadow-md bg-white gap-3 flex-1').style('width: 72%; border-color: #E2E8F0;'):
                            self.plot_view = SpectrumPlotContainer(backend_service)
                        with ui.card().classes('p-4 rounded-lg border shadow-md bg-zinc-900 gap-3 text-white').style('width: 28%; max-width: 340px;'):
                            self.sidebar = ControlPanelSidebar(backend_service, self.plot_view)

                with ui.tab_panel(self.tab_recording).classes('p-0 m-0 bg-transparent'):
                    SpectrumRecordingPanel(backend_service)

                with ui.tab_panel(self.tab_hardware).classes('p-0 m-0 bg-transparent'):
                    self.calibration_panel = HardwareCalibrationPanel(backend_service.system, title_sync_callback=self.update_browser_tab_title)

    def global_ui_sync_tick(self):
        """Drives all real-time component updates and handles dynamic layout changes."""
        hardware_ok = backend_service.is_hardware_available
        current_status = backend_service.status_text
        
        current_sys_id = backend_service.system.hw_profile.get('SYS-ID', 'SYS-STANDBY')
        current_serial = backend_service.system.serial_number
        
        # High-frequency logging trace loop matching statements
        logger.info(f"[UI_SYNC_LOOP] available={hardware_ok} | serial={current_serial} | msg='{current_status}'")

        # Update node status badge values (with operator guidance modification)
        if current_serial != "UNKNOWN":
            self.station_id_badge.set_text(f"Station: {current_sys_id}")
        else:
            self.station_id_badge.set_text(f"Station: {current_sys_id} (looking for hardware...)")

        # FIXED: Reactive hot-plug browser tab title adjustment
        if self.current_applied_sys_id != current_sys_id:
            logger.warning(f"[UI_SYNC] Dynamic profile shift detected in title string context ({self.current_applied_sys_id} -> {current_sys_id}). Re-writing window title...")
            self.update_browser_tab_title()

        # Robust direct object validation pattern bypasses container iteration completely
        if self.calibration_panel is not None:
            if self.calibration_panel.last_bound_serial != current_serial:
                logger.info(f"[UI_SYNC] Hardware discovery state transition detected. Forcing configuration fields update...")
                self.calibration_panel.refresh_all_inputs()

        # Sync subpanel layout charts states
        if self.sidebar is not None and self.plot_view is not None:
            self.sidebar.refresh_widget_states()
            self.plot_view.update_ui_elements()

        # Handle responsive layout mutations on hot-plug operations
        if hardware_ok:
            self.connection_alert_banner.classes(add='bg-green-50 border-green-200 text-green-800', remove='bg-red-50 border-red-200 text-red-800')
            self.banner_icon.set_visibility(False)
            self.banner_text.set_text(f"Hardware connection online: {current_status}")
            self.banner_status_pill.set_text("ONLINE").classes(add='bg-green-100 text-green-800', remove='bg-red-100 text-red-800')
        else:
            self.connection_alert_banner.classes(add='bg-red-50 border-red-200 text-red-800', remove='bg-green-50 border-green-200 text-green-800')
            self.banner_icon.set_visibility(True).style("color: #B9222D;")
            self.banner_text.set_text("⚠️ MCA HARDWARE CRITICAL FAILURE: Connection broken or device disconnected. Checking port link auto-discovery loop...")
            self.banner_status_pill.set_text("DISCONNECTED").classes(add='bg-red-100 text-red-800', remove='bg-green-100 text-green-800')

        # Master layout tick loop evaluation statement
        if backend_service.hardware_sync_required and backend_service.is_hardware_available:
            logger.warning("[UI_TICK] Active sync required state is flagged. Redirecting execution to board programming logic...")
            backend_service.push_active_profile_to_board()


@ui.page('/')
def index():
    RIIDSpectroscopyApp()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="RIID Gamma Spectroscopy Station", port=8080)
