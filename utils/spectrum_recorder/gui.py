from nicegui import ui
from state_engine import SpectrumAcquisitionSystem
from config import BRAND_COLORS
import gui_backend

# 1. Instantiate physics core state layers
system = SpectrumAcquisitionSystem()
system.probe_device()

def assemble_ultra_compact_workspace():
    """Assembles a dense, side-by-side zero-scroll context for laboratory screens."""
    # MAIN WORKSPACE ROW WRAPPER
    with ui.row().classes('w-full p-2 gap-2 items-stretch no-wrap'):
        
        # LEFT CARD: Parameter Data Entry Matrices (w-[49%])
        with ui.card().classes('flex-1 p-3 rounded-lg border shadow-sm bg-white gap-1').style('width: 49%;'):
            ui.label('Measurement Parameters').classes('text-sm font-bold').style(f"color: {BRAND_COLORS['primary']};")
            
            with ui.tabs().classes('w-full dense border-b').style(f"color: {BRAND_COLORS['secondary']};") as panel_tabs:
                tab_experimental = ui.tab('Experiment settings').classes('text-xs p-1')
                tab_calibration = ui.tab('Hardware & Calibration').classes('text-xs p-1')

            with ui.tab_panels(panel_tabs, value=tab_experimental).classes('w-full bg-transparent p-0 pt-2'):
                with ui.tab_panel(tab_experimental).classes('space-y-1 p-0'):
                    gui_backend.render_volatile_environment_tab(system)
                
                gui_backend.render_calibration_persistent_panel(system, tab_calibration)
                
        # RIGHT CARD: Interactive Plotly Canvas & Execution Triggers (w-[49%])
        with ui.card().classes('flex-1 p-3 rounded-lg border shadow-sm bg-white gap-1').style('width: 49%;'):
            plot_container = ui.column().classes('w-full items-center justify-center rounded-lg border').style('background-color: #FFFFFF; border-color: #F3F4F6;')
            
            # Formulate and append views modules sequentially
            gui_backend.update_interactive_plotly_canvas(system, plot_container, [])
            gui_backend.render_acquisition_telemetry_commands(system, plot_container)


# Framework execution multiprocessing safety guards block context
if __name__ in {"__main__", "__mp_main__"}:
    assemble_ultra_compact_workspace()
    ui.run(title="RIID Gamma Spectrometry Hub", port=8080)
