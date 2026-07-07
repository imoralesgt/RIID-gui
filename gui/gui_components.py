from nicegui import ui
from config import BRAND_COLORS
from riid_service import RIIDCoreService

class SpectrumPlotContainer:
    def __init__(self, service: RIIDCoreService):
        self.service = service
        self.container = ui.column().classes('w-full items-center justify-center rounded-lg border p-1 bg-white')
        
        self.riid_label = ui.label("ID: Standby").classes('text-2xl font-black uppercase tracking-wide px-2 py-1 rounded w-full')
        self.riid_label.style(f"color: {BRAND_COLORS['crimson_trace']}; background-color: #FEF2F2; border-left: 5px solid {BRAND_COLORS['crimson_trace']};")

    def update_ui_elements(self):
        self.riid_label.set_text(f"ID: {self.service.current_isotope_id}")
        self.container.clear()
        spectrum_data = self.service.live_spectrum
        
        if not spectrum_data:
            with self.container, ui.column().classes('w-full h-[320px] items-center justify-center p-4 text-center text-zinc-400 gap-1'):
                ui.icon('analytics', size='lg').style(f"color: {BRAND_COLORS['accent']};")
                ui.label("Spectrometer Offline / Ready").classes('text-xs font-bold text-zinc-700')
            return

        num_channels = len(spectrum_data)
        a0, a1, a2 = self.service.system.hw_profile['calib_a0'], self.service.system.hw_profile['calib_a1'], self.service.system.hw_profile['calib_a2']
        energy_axis = [a0 + (a1 * ch) + (a2 * (ch ** 2)) for ch in range(num_channels)]
        
        fig = {
            'data': [{'x': energy_axis, 'y': spectrum_data, 'type': 'scatter', 'mode': 'lines', 'line': {'color': BRAND_COLORS['crimson_trace'], 'width': 1.2}}],
            'layout': {
                'xaxis': {'title': 'Energy (keV)', 'tickfont': {'size': 8}, 'gridcolor': '#E5E7EB', 'autorange': True},
                'yaxis': {'title': 'Counts', 'type': 'log', 'tickfont': {'size': 8}, 'gridcolor': '#E5E7EB'},
                'margin': {'l': 40, 'r': 15, 't': 10, 'b': 30}, 'plot_bgcolor': '#FFFFFF', 'paper_bgcolor': '#FFFFFF', 'showlegend': False
            }
        }
        with self.container:
            ui.plotly(fig).classes('w-full h-[320px]')


class ControlPanelSidebar:
    def __init__(self, service: RIIDCoreService, plot_container: SpectrumPlotContainer):
        self.service = service
        self.plot_container = plot_container
        self._assemble_ui()

    def _assemble_ui(self):
        with ui.column().classes('w-full gap-3 p-1'):
            ui.label('Survey Orchestration').classes('text-xs font-bold text-zinc-700 uppercase tracking-wider')
            
            self.bg_time_input = ui.number('BG Record Time (s)', value=30, format='%d').props('dense outlined').classes('w-full text-xs')
            self.min_cnt_input = ui.number('ML Min Counts', value=2000, format='%d').props('dense outlined').classes('w-full text-xs')
            self.max_cnt_input = ui.number('Hysteresis Max Counts', value=15000, format='%d').props('dense outlined').classes('w-full text-xs')

            # Real-time state indicators
            with ui.column().classes('w-full p-2 bg-zinc-50 border rounded gap-0.5 font-mono text-[11px] text-zinc-600'):
                self.status_lbl = ui.label('Status: Syncing...')
                self.bg_status_lbl = ui.label('Background: Missing')

            # High-Visibility Dedicated Background Action Call Trigger
            self.bg_btn = ui.button('RECORD BACKGROUND', icon='shield', on_click=self.trigger_bg)
            self.bg_btn.style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").props('dense').classes('w-full py-1 text-xs')
            
            # Survey Action Control Hub
            with ui.row().classes('w-full gap-1 no-wrap'):
                self.start_btn = ui.button(icon='play_arrow', on_click=self.trigger_start)
                self.start_btn.style("background-color: #10B981;").props('dense').classes('flex-1')
                
                self.stop_btn = ui.button(icon='stop', on_click=self.service.stop_execution)
                self.stop_btn.style("background-color: #EF4444;").props('dense').classes('flex-1')
                
                self.reset_btn = ui.button(icon='refresh', on_click=self.service.reset_service_state)
                self.reset_btn.style(f"background-color: {BRAND_COLORS['secondary']};").props('dense').classes('flex-1')

    def trigger_bg(self):
        self.service.start_background_recording(int(self.bg_time_input.value or 30))

    def trigger_start(self):
        self.service.min_counts_trigger = int(self.min_cnt_input.value or 2000)
        self.service.max_counts_limit = int(self.max_cnt_input.value or 15000)
        self.service.start_continuous_survey()

    def refresh_widget_states(self):
        """Synchronizes action trigger elements based on persistent background core state."""
        self.status_lbl.set_text(f"Status: {self.service.status_text}")
        
        is_idle = self.service.state == 'IDLE'
        hw_ok = self.service.is_hardware_available
        has_bg = len(self.service.background_spectrum) > 0

        # Sync background metadata readout status line
        if has_bg:
            self.bg_status_lbl.set_text("Background: Captured Profile Ready")
            self.bg_status_lbl.style("color: #10B981;")
        else:
            self.bg_status_lbl.set_text("Background: Profile Missing")
            self.bg_status_lbl.style("color: #EF4444;")

        # Apply safety locks to buttons
        self.bg_btn.set_visibility(is_idle and hw_ok)
        self.start_btn.set_visibility(is_idle and hw_ok and has_bg)
        self.stop_btn.set_visibility(not is_idle)
        self.reset_btn.set_visibility(is_idle)
