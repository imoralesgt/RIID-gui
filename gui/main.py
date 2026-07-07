from nicegui import app, ui
from config import BRAND_COLORS
from riid_service import RIIDCoreService
from gui_components import SpectrumPlotContainer, ControlPanelSidebar

# Instantiate the engine cleanly without executing raw global I/O ops
backend_service = RIIDCoreService()

async def runtime_bootstrap_sequence():
    """Sequentially handles dynamic device discovery and background service loop tasks."""
    await backend_service.initialize_and_probe()
    backend_service.start_service_loops()

# Register the boot routine with the NiceGUI lifecycle manager
app.on_startup(runtime_bootstrap_sequence)

class RIIDSpectroscopyApp:
    def __init__(self):
        self.build_workspace()

    def build_workspace(self):
        ui.colors(primary=BRAND_COLORS['primary'], secondary=BRAND_COLORS['secondary'])
        
        with ui.column().classes('w-full p-2 bg-slate-100 min-h-screen gap-2'):
            ui.markdown("### ⚛️ IAEA RIID Laboratory Spectroscopy Station").classes('text-sm font-bold text-zinc-800 m-0 p-0')

            with ui.row().classes('w-full gap-2 items-stretch no-wrap flex-1'):
                # Left Column: Interactive Spectrum Area and Target ML Label
                with ui.card().classes('p-3 rounded-lg border shadow-sm bg-white gap-2 flex-1').style('width: 72%;'):
                    self.plot_view = SpectrumPlotContainer(backend_service)

                # Right Column: Counting Parameters and Core Interlocking Triggers
                with ui.card().classes('p-3 rounded-lg border shadow-sm bg-white gap-2').style('width: 28%; max-width: 320px;'):
                    self.sidebar = ControlPanelSidebar(backend_service, self.plot_view)

        def global_ui_sync_tick():
            self.sidebar.refresh_widget_states()
            self.plot_view.update_ui_elements()
            
        ui.timer(1.0, global_ui_sync_tick)

@ui.page('/')
def index():
    RIIDSpectroscopyApp()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="RIID Gamma Spectrometry Hub", port=8080)
