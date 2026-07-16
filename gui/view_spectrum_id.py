import os
import json
import math
from nicegui import ui
from config import BRAND_COLORS, get_rgba_fill, logger

class SpectrumPlotContainer:
    def __init__(self, service):
        self.service = service
        self.container = ui.column().classes('w-full items-center justify-center rounded-lg border p-2 bg-white')
        self.riid_label = ui.label("ID: Standby").classes('text-2xl font-black uppercase tracking-wide px-3 py-2 rounded w-full border')
        self.riid_label.style(f"color: {BRAND_COLORS['crimson_trace']}; background-color: #FEF2F2; border-color: #FEE2E2; border-left: 6px solid {BRAND_COLORS['crimson_trace']};")

    def update_ui_elements(self):
        """Master orchestrator driving dynamic component layers stacking order and layout configurations."""
        self.riid_label.set_text(f"ID: {self.service.current_isotope_id}")
        self.container.clear()
        
        spectrum_data = self.service.live_spectrum
        bg_data = self.service.background_spectrum
        current_state = self.service.state
        use_log = getattr(self.service, 'use_log_scale', True)
        
        # Guard: If no spectrum data is captured anywhere, draw the standby splash card
        if not spectrum_data and not bg_data:
            with self.container, ui.column().classes('w-full h-[360px] items-center justify-center p-4 text-center text-zinc-400 gap-1'):
                ui.icon('analytics', size='lg').style(f"color: {BRAND_COLORS['accent']};")
                ui.label("Spectrometer Standby - Click Start on Console").classes('text-xs font-bold text-zinc-700')
            return

        # 1. Resolve channel dimensions cleanly to manage mapping sizes
        show_frozen_survey = getattr(self.service, 'survey_stopped_with_data', False)
        live_trace_active = spectrum_data and (current_state == 'ACQUIRING_SURVEY' or show_frozen_survey)
        num_channels = len(spectrum_data) if live_trace_active else len(bg_data)
        if num_channels == 0 and spectrum_data:
            num_channels = len(spectrum_data)
            
        energy_axis = self._get_energy_axis(num_channels)
        
        # 2. Lifecycle step: Calculate the active real-time CPS metrics directly from MCA timers
        cps_val_string = "0.00"
        if (current_state == 'ACQUIRING_SURVEY' or show_frozen_survey) and spectrum_data:
            total_cts = sum(spectrum_data)
            survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
            survey_secs = float(survey_ms / 1000.0)
            if survey_secs > 0.0:
                cps_val_string = f"{float(total_cts / survey_secs):.2f}"

        # Initialize trace list matrix
        plotly_traces = []
        peak_y_value = 0.0
        
        # 3. FIXED LAYER STACK: Append the live blue survey trace FIRST so it acts as the bottom layer
        peak_y_value = self._append_live_survey_trace(
            plotly_traces, energy_axis, spectrum_data, current_state, use_log, peak_y_value, num_channels, cps_val_string
        )
        
        # 4. FIXED LAYER STACK: Append the environmental background baseline SECOND to layer it on top
        peak_y_value = self._append_background_trace(
            plotly_traces, energy_axis, spectrum_data, bg_data, current_state, use_log, num_channels
        )
        
        # 5. Modular calculations: Determine the fluid vertical chart display constraints
        y_axis_layout = self._calculate_y_axis_layout(use_log, peak_y_value)

        fig = {
            'data': plotly_traces,
            'layout': {
                'xaxis': {'title': 'Energy (keV)', 'titlefont': {'size': 10, 'bold': True}, 'tickfont': {'size': 8}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True},
                'yaxis': y_axis_layout,
                'margin': {'l': 45, 'r': 20, 't': 15, 'b': 35}, 
                'plot_bgcolor': BRAND_COLORS['plot_bg'], 
                'paper_bgcolor': BRAND_COLORS['plot_paper'], 
                'showlegend': True,
                'barmode': 'overlay',
                'legend': {'font': {'size': 8}, 'x': 0.70, 'y': 0.95, 'bgcolor': get_rgba_fill('legend_bg', alpha=0.7)}
            }
        }
        with self.container:
            ui.plotly(fig).classes('w-full h-[360px]')


    def _get_energy_axis(self, num_channels: int) -> list:
        """Parses active hardware slope parameters and compiles keV coordinates."""
        prof = self.service.system.hw_profile
        a0 = float(prof.get('calib_a0') if prof.get('calib_a0') is not None else 0.0)
        a1 = float(prof.get('calib_a1') if prof.get('calib_a1') is not None else 1.0)
        a2 = float(prof.get('calib_a2') if prof.get('calib_a2') is not None else 0.0)
        return [a0 + (a1 * ch) + (a2 * (ch ** 2)) for ch in range(num_channels)]

    def _append_background_trace(self, traces: list, x_axis: list, spectrum_data: list, bg_data: list, state: str, use_log: bool, num_channels: int) -> float:
        """Calculates dynamic hardware-timed proportional baseline corrections and conditionally configures area shading layers."""
        peak_y = 0.0
        target_raw_y = None
        trace_name = "Environmental Background Baseline"
        
        if state == 'BG_RECORDING' and spectrum_data:
            target_raw_y = spectrum_data
            trace_name = "Recording Live Background..."
        elif bg_data and len(bg_data) == num_channels:
            bg_ms = float(getattr(self.service, 'bg_hardware_live_time_ms', 30000.0) or 30000.0)
            if state == 'ACQUIRING_SURVEY':
                survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
                time_scaling_factor = float(survey_ms / bg_ms)
                trace_name = f"Background Baseline (Normalized to {survey_ms/1000:.1f}s)"
            else:
                time_scaling_factor = 1.0
                trace_name = f"Background Baseline ({bg_ms/1000:.1f}s Reference)"
                
            raw_scaled_bg = [float(counts * time_scaling_factor) for counts in bg_data]
            target_raw_y = raw_scaled_bg

        if target_raw_y is not None and len(target_raw_y) == num_channels:
            peak_y = float(max(target_raw_y)) if target_raw_y else 0.0
            processed_bg_y = [v if v > 0 else 0.1 for v in target_raw_y] if use_log else target_raw_y
            
            if use_log:
                # FIXED MODIFICATION: Remove background area shade completely when in log scale
                traces.append({
                    'x': x_axis, 
                    'y': processed_bg_y, 
                    'type': 'scatter', 
                    'mode': 'lines', 
                    'name': trace_name,
                    'line': {'color': BRAND_COLORS['accent'], 'width': 1.2},
                    'opacity': 0.85
                })
            else:
                # Linear scale continues to run cleanly utilizing a pale translucent gray area fill
                shading_fill_color = get_rgba_fill('accent', alpha=0.20)
                traces.append({
                    'x': x_axis, 
                    'y': processed_bg_y, 
                    'type': 'scatter', 
                    'mode': 'lines', 
                    'name': trace_name,
                    'line': {'color': BRAND_COLORS['accent'], 'width': 1.4},
                    'fill': 'tozeroy', 
                    'fillcolor': shading_fill_color, 
                    'opacity': 0.95
                })
            
        return peak_y

    def _append_live_survey_trace(self, traces: list, x_axis: list, spectrum_data: list, state: str, use_log: bool, current_peak_y: float, num_channels: int, cps_string: str) -> float:
        """Applies safe log filters and overlays the main active survey line with integrated label CPS readouts and scale-dependent shading."""
        peak_y = current_peak_y
        
        if spectrum_data and len(spectrum_data) == num_channels and sum(spectrum_data) > 0 and \
           (state == 'ACQUIRING_SURVEY' or getattr(self.service, 'survey_stopped_with_data', False)):
            live_max = float(max(spectrum_data))
            if live_max > peak_y:
                peak_y = live_max
                
            processed_live_y = [val if val > 0 else 0.1 for val in spectrum_data] if use_log else spectrum_data
            
            # FIXED: Dynamically embed the current CPS metrics straight into the plot trace name label string
            if state == 'ACQUIRING_SURVEY':
                legend_label_name = f"Live Survey Session ({cps_string} CPS)"
            else:
                legend_label_name = f"Last Survey (Stopped, {cps_string} CPS)"
            
            if use_log:
                # FIXED MODIFICATION: No area shading fill is added under the curve when in log scale
                traces.append({
                    'x': x_axis, 
                    'y': processed_live_y, 
                    'type': 'scatter', 
                    'mode': 'lines', 
                    'name': legend_label_name,
                    'layer': 'below',
                    'line': {'color': BRAND_COLORS['primary'], 'width': 1.8}
                })
            else:
                # FIXED MODIFICATION: Add pale transparent blue area-under-the-curve shade only in linear scale
                # Programmatically generate transparent blue from our centralized primary color hex key
                primary_shading_fill = get_rgba_fill('primary', alpha=0.15)
                
                traces.append({
                    'x': x_axis, 
                    'y': processed_live_y, 
                    'type': 'scatter', 
                    'mode': 'lines', 
                    'name': legend_label_name,
                    'layer': 'below',
                    'line': {'color': BRAND_COLORS['primary'], 'width': 1.8},
                    'fill': 'tozeroy',
                    'fillcolor': primary_shading_fill
                })
            
        return peak_y




    def _calculate_y_axis_layout(self, use_log: bool, peak_y_value: float) -> dict:
        """Configures a pure native Plotly auto-scaling layout box format preventing integer compression."""
        axis_title_string = 'Counts'
        
        if use_log:
            # FIXED: Bypasses manual calculation limits. Leverages native Plotly autorange tracking 
            # while binding strict formatting rules to force base-10 power of ten index grid lines.
            return {
                'title': axis_title_string,
                'type': 'log',
                'titlefont': {'size': 10, 'bold': True},
                'tickfont': {'size': 8},
                'gridcolor': BRAND_COLORS['plot_grid'],
                
                # Grants Plotly absolute native freedom to expand ceilings dynamically past 100, 1000, or higher
                'autorange': True,
                
                # Clean lower boundary constraint locks the view starting at 10^0 (1 count floor)
                'range': [0, None],
                
                # Forces Plotly to place major tick grid lines strictly on whole decade step integers
                'dtick': 1,
                
                # Mutes fractional floating-point labels (e.g., prevents 10^-0.5 or 10^0.5 artifacts)
                'tickformat': '.0f'
            }
        else:
            # Linear scale continue to run on native automatic scaling properties
            return {
                'title': axis_title_string,
                'type': 'linear',
                'titlefont': {'size': 10, 'bold': True},
                'tickfont': {'size': 8},
                'gridcolor': BRAND_COLORS['plot_grid'],
                'autorange': True
            }


class ControlPanelSidebar:
    def __init__(self, service, plot_container: SpectrumPlotContainer):
        self.service = service
        self.plot_container = plot_container
        if not hasattr(self.service, 'use_log_scale'):
            self.service.use_log_scale = False
        self._assemble_ui()

    def _assemble_ui(self):
        with ui.column().classes('w-full gap-4 text-slate-200'):
            ui.label('Survey Control Console').classes('text-xs font-bold text-zinc-400 uppercase tracking-widest border-b pb-1 w-full border-zinc-700')
            
            with ui.column().classes('w-full gap-2 bg-zinc-800 p-3 rounded-md border border-zinc-700 shadow-inner'):
                self.min_cnt_input = ui.number('ML Detection Threshold (cts)', value=self.service.min_counts_trigger, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')
                self.max_cnt_input = ui.number('Hysteresis Cycle Reset (cts)', value=self.service.max_counts_limit, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')
                self.bg_time_input = ui.number('BG Record Time (s)', value=self.service.bg_target_time, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')
                
                self.scale_checkbox = ui.checkbox(
                    'Log-scale', 
                    value=self.service.use_log_scale,
                    on_change=lambda e: self._toggle_plot_scale(e.value)
                ).classes('text-xs text-zinc-300 font-medium mt-1')

            with ui.column().classes('w-full p-3 bg-black border border-zinc-800 rounded-md gap-1 font-mono text-xs text-emerald-400'):
                self.status_lbl = ui.label('SYSTEM: Syncing...')
                self.bg_status_lbl = ui.label('BACKGROUND: Missing Profile')
                
            self.bg_progress_bar = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-1.5 rounded transition-all').props('color=amber')
            self.bg_progress_bar.set_visibility(False)

            self.bg_btn = ui.button('RECORD BACKGROUND PROFILE', icon='security', on_click=self.trigger_bg)
            self.bg_btn.style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").props('dense').classes('w-full py-2 text-xs shadow-md')
            
            with ui.row().classes('w-full gap-2 no-wrap pt-1'):
                self.play_stop_btn = ui.button('START', icon='play_arrow', on_click=self.trigger_play_stop_toggle)
                self.play_stop_btn.style("background-color: #10B981; font-weight: bold;").props('dense').classes('flex-1 py-1.5')
                self.clear_btn = ui.button('CLEAR', icon='delete_sweep', on_click=self.trigger_clear)
                self.clear_btn.style(f"background-color: {BRAND_COLORS['secondary']}; border: 1px solid #4A5568;").props('dense').classes('flex-1 py-1.5')

    def _toggle_plot_scale(self, value: bool):
        logger.info(f"[USER_ACTION] Operator modified counts scaling preference selection -> use_log_scale={value}")
        self.service.use_log_scale = value

    def trigger_bg(self):
        logger.warning(f"[USER_ACTION] Operator clicked RECORD BACKGROUND PROFILE button. Duration: {self.bg_time_input.value}s")
        self.service.start_background_recording(int(self.bg_time_input.value or 30))

    def trigger_play_stop_toggle(self):
        """Single control that starts a survey when idle, or halts it when running.
        Replaces the old separate START/STOP/CLEAR buttons - STOP no longer wipes
        the spectrum, so a dedicated RESTART/CLEAR action is unnecessary."""
        if self.service.state == 'IDLE':
            self.trigger_start()
        else:
            self.trigger_stop()

    def trigger_start(self):
        logger.warning(f"[USER_ACTION] Operator clicked START continuous survey. trigger={self.min_cnt_input.value} cts | reset={self.max_cnt_input.value} cts")
        self.service.min_counts_trigger = int(self.min_cnt_input.value or 2000)
        self.service.max_counts_limit = int(self.max_cnt_input.value or 15000)
        self.service.start_continuous_survey()

    def trigger_stop(self):
        logger.warning("[USER_ACTION] Operator clicked STOP survey button.")
        self.service.stop_execution()

    def trigger_clear(self):
        logger.warning("[USER_ACTION] Operator clicked CLEAR button - wiping accumulated survey spectrum (background preserved).")
        self.service.clear_survey_data()

    def refresh_widget_states(self):
        """Monitors status variables and dynamically updates the panel metrics text strings."""
        is_idle = self.service.state == 'IDLE'
        is_bg_running = self.service.state == 'BG_RECORDING'
        is_survey_running = self.service.state == 'ACQUIRING_SURVEY'
        hw_ok = self.service.is_hardware_available
        has_bg = len(self.service.background_spectrum) > 0

        # Calculate exact Counts Per Second (CPS) metrics based directly on MCA hardware live-time
        if is_survey_running and self.service.live_spectrum:
            total_counts = sum(self.service.live_spectrum)
            # Fetch active survey live-time duration in milliseconds directly from the MCA hardware
            survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
            survey_seconds = float(survey_ms / 1000.0)
            
            # Safe boundary division check calculates precise CPS rate values
            cps_rate = float(total_counts / survey_seconds) if survey_seconds > 0.0 else 0.0
            
            # FIXED: Formally display the calculated hardware CPS metric on the panel view label
            self.status_lbl.set_text(
                f"OP_STATE: SURVEY ACTIVE | TIME: {survey_seconds:.1f}s | "
                f"COUNTS: {total_counts} | RATE: {cps_rate:.2f} CPS"
            )
        else:
            self.status_lbl.set_text(f"OP_STATE: {self.service.status_text.upper()}")

        if has_bg:
            self.bg_status_lbl.set_text("BACKGROUND PROFILE: CALIBRATED (READY)")
            self.bg_status_lbl.style("color: #34D399;")
        else:
            self.bg_status_lbl.set_text("BACKGROUND PROFILE: ABSENT (LOCKED)")
            self.bg_status_lbl.style("color: #F87171;")

        if is_bg_running:
            self.bg_progress_bar.set_visibility(True)
            prog_val = getattr(self.service, 'bg_progress', 0.0)
            self.bg_progress_bar.set_value(prog_val)
        else:
            self.bg_progress_bar.set_visibility(False)
            self.bg_progress_bar.set_value(0.0)

        self.bg_btn.set_visibility(is_idle and hw_ok)

        # Single toggle button: shows START when idle (ready to run), STOP while a
        # survey/background/batch run is in progress. No separate RESTART/CLEAR
        # control - STOP no longer erases the spectrum, so it isn't needed.
        if is_idle:
            self.play_stop_btn.set_text('START')
            self.play_stop_btn.props('icon=play_arrow')
            self.play_stop_btn.style("background-color: #10B981; font-weight: bold;")
        else:
            self.play_stop_btn.set_text('STOP')
            self.play_stop_btn.props('icon=stop')
            self.play_stop_btn.style("background-color: #EF4444; font-weight: bold;")

        self.play_stop_btn.set_visibility((is_idle and hw_ok and has_bg) or not is_idle)

        # CLEAR only touches the accumulated survey spectrum. It stays available
        # both when idle and during an active survey so it doesn't require STOP
        # first; it's hidden only during BG recording / batch runs where clearing
        # would be ambiguous or unsafe.
        self.clear_btn.set_visibility(is_idle or is_survey_running)