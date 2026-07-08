from nicegui import app, ui
from config import BRAND_COLORS
from riid_service import RIIDCoreService
from view_spectrum_id import SpectrumPlotContainer, ControlPanelSidebar
from view_recording import SpectrumRecordingPanel
from view_calibration import HardwareCalibrationPanel

backend_service = RIIDCoreService()

async def runtime_bootstrap_sequence():
    await backend_service.initialize_and_probe()
    backend_service.start_service_loops()

app.on_startup(runtime_bootstrap_sequence)

class RIIDSpectroscopyApp:
    def __init__(self):
        self.build_workspace()

    def build_workspace(self):
        ui.colors(primary=BRAND_COLORS['primary'], secondary=BRAND_COLORS['secondary'])
        
        with ui.column().classes('w-full p-3 min-h-screen gap-3').style(f"background-color: {BRAND_COLORS['bg_workspace']}; font-family: 'Roboto', sans-serif;"):
            
            with ui.row().classes('w-full justify-between items-center px-2 py-1 border-b').style("border-color: #D1D5DB;"):
                ui.markdown(f"### **IAEA** RIID Laboratory Spectroscopy Station").classes('text-base font-bold text-slate-800 m-0 p-0')
                
                # REVERTED & CLEANED: Simply draw the reactive text handle tracking backend profile memory
                self.node_id_label = ui.label("Station Node: Syncing S/N...").classes('text-xs font-mono font-bold px-3 py-1 rounded bg-white shadow-sm border text-blue-700 border-blue-200')

            with ui.card().classes('w-full p-0 rounded-lg border shadow-sm no-wrap overflow-hidden').style("background-color: #2D3748; border-color: #1A202C;"):
                with ui.tabs().classes('w-full dense text-white') as self.main_tabs:
                    self.tab_id = ui.tab('Spectrum ID', icon='analytics').classes('text-xs font-bold py-2')
                    self.tab_recording = ui.tab('Spectrum Recording', icon='save_alt').classes('text-xs font-bold py-2')
                    self.tab_hardware = ui.tab('Hardware & Calibration', icon='tune').classes('text-xs font-bold py-2')

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
                    HardwareCalibrationPanel(backend_service.system)

        def global_ui_sync_tick():
            if hasattr(self, 'sidebar') and hasattr(self, 'plot_view'):
                self.sidebar.refresh_widget_states()
                self.plot_view.update_ui_elements()
                
                # RE-EVALUATE HARDWARE PROFILES DIRECTLY DURING TICKS
                current_sys_id = backend_service.system.hw_profile.get('SYS-ID', 'SYS-STANDBY')
                self.node_id_label.set_text(f"Station Node: {current_sys_id}")
            
        ui.timer(1.0, global_ui_sync_tick)

@ui.page('/')
def index():
    RIIDSpectroscopyApp()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="RIID Gamma Spectroscopy Station", port=8080)
