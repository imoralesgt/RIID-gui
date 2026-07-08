import os
import json
from nicegui import ui
from config import BRAND_COLORS

class SpectrumPlotContainer:
    def __init__(self, service):
        self.service = service
        self.container = ui.column().classes('w-full items-center justify-center rounded-lg border p-2 bg-white')
        self.riid_label = ui.label("ID: Standby").classes('text-2xl font-black uppercase tracking-wide px-3 py-2 rounded w-full border')
        self.riid_label.style(f"color: {BRAND_COLORS['crimson_trace']}; background-color: #FEF2F2; border-color: #FEE2E2; border-left: 6px solid {BRAND_COLORS['crimson_trace']};")

    def update_ui_elements(self):
        """Periodic sync callback invoked by display loop ticks to refresh layout data."""
        self.riid_label.set_text(f"ID: {self.service.current_isotope_id}")
        self.container.clear()
        spectrum_data = self.service.live_spectrum
        
        if not spectrum_data:
            with self.container, ui.column().classes('w-full h-[360px] items-center justify-center p-4 text-center text-zinc-400 gap-1'):
                ui.icon('analytics', size='lg').style(f"color: {BRAND_COLORS['accent']};")
                ui.label("Spectrometer Standby - Click Start on Console").classes('text-xs font-bold text-zinc-700')
            return

        num_channels = len(spectrum_data)
        prof = self.service.system.hw_profile
        a0 = float(prof.get('calib_a0', 0.0))
        a1 = float(prof.get('calib_a1', 1.0))
        a2 = float(prof.get('calib_a2', 0.0))
        energy_axis = [a0 + (a1 * ch) + (a2 * (ch ** 2)) for ch in range(num_channels)]
        
        # FIG CONSTRUCTOR SYNCHRONIZATION MATRIX
        fig = {
            # MODIFIED: Swapped color metric pointer reference from 'crimson_trace' to 'primary'
            'data': [{'x': energy_axis, 'y': spectrum_data, 'type': 'scatter', 'mode': 'lines', 'line': {'color': BRAND_COLORS['primary'], 'width': 1.5}}],
            'layout': {
                'xaxis': {'title': 'Energy (keV)', 'titlefont': {'size': 10, 'bold': True}, 'tickfont': {'size': 8}, 'gridcolor': '#E5E7EB', 'autorange': True},
                'yaxis': {'title': 'Counts (Log)', 'type': 'log', 'titlefont': {'size': 10, 'bold': True}, 'tickfont': {'size': 8}, 'gridcolor': '#E5E7EB'},
                'margin': {'l': 45, 'r': 20, 't': 15, 'b': 35}, 'plot_bgcolor': '#FFFFFF', 'paper_bgcolor': '#FFFFFF', 'showlegend': False
            }
        }
        with self.container:
            ui.plotly(fig).classes('w-full h-[360px]')



class ControlPanelSidebar:
    def __init__(self, service, plot_container: SpectrumPlotContainer):
        self.service = service
        self.plot_container = plot_container
        self._assemble_ui()

    def _assemble_ui(self):
        with ui.column().classes('w-full gap-4 text-slate-200'):
            ui.label('Survey Control Console').classes('text-xs font-bold text-zinc-400 uppercase tracking-widest border-b pb-1 w-full border-zinc-700')
            
            with ui.column().classes('w-full gap-2 bg-zinc-800 p-3 rounded-md border border-zinc-700 shadow-inner'):
                self.min_cnt_input = ui.number('ML Detection Threshold (cts)', value=self.service.min_counts_trigger, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')
                self.max_cnt_input = ui.number('Hysteresis Cycle Reset (cts)', value=self.service.max_counts_limit, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')
                self.bg_time_input = ui.number('BG Record Time (s)', value=self.service.bg_target_time, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')

            with ui.column().classes('w-full p-3 bg-black border border-zinc-800 rounded-md gap-1 font-mono text-xs text-emerald-400'):
                self.status_lbl = ui.label('SYSTEM: Syncing...')
                self.bg_status_lbl = ui.label('BACKGROUND: Missing Profile')

            self.bg_btn = ui.button('RECORD BACKGROUND PROFILE', icon='security', on_click=self.trigger_bg)
            self.bg_btn.style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").props('dense').classes('w-full py-2 text-xs shadow-md')
            
            with ui.row().classes('w-full gap-2 no-wrap pt-1'):
                self.start_btn = ui.button('START', icon='play_arrow', on_click=self.trigger_start)
                self.start_btn.style("background-color: #10B981; font-weight: bold;").props('dense').classes('flex-1 py-1.5')
                self.stop_btn = ui.button('STOP', icon='stop', on_click=self.service.stop_execution)
                self.stop_btn.style("background-color: #EF4444; font-weight: bold;").props('dense').classes('flex-1 py-1.5')
                self.reset_btn = ui.button('CLEAR', icon='refresh', on_click=self.service.reset_service_state)
                self.reset_btn.style(f"background-color: {BRAND_COLORS['secondary']}; border: 1px solid #4A5568;").props('dense').classes('flex-1 py-1.5')

    def trigger_bg(self):
        self.service.start_background_recording(int(self.bg_time_input.value or 30))

    def trigger_start(self):
        self.service.min_counts_trigger = int(self.min_cnt_input.value or 2000)
        self.service.max_counts_limit = int(self.max_cnt_input.value or 15000)
        self.service.start_continuous_survey()

    def refresh_widget_states(self):
        self.status_lbl.set_text(f"OP_STATE: {self.service.status_text.upper()}")
        is_idle = self.service.state == 'IDLE'
        hw_ok = self.service.is_hardware_available
        has_bg = len(self.service.background_spectrum) > 0

        if has_bg:
            self.bg_status_lbl.set_text("BG_PROFILE: CALIBRATED (READY)")
            self.bg_status_lbl.style("color: #34D399;")
        else:
            self.bg_status_lbl.set_text("BG_PROFILE: ABSENT (LOCKED)")
            self.bg_status_lbl.style("color: #F87171;")

        self.bg_btn.set_visibility(is_idle and hw_ok)
        self.start_btn.set_visibility(is_idle and hw_ok and has_bg)
        self.stop_btn.set_visibility(not is_idle)
        self.reset_btn.set_visibility(is_idle)
