import os
import json
import math
from datetime import datetime, timezone
from nicegui import ui
from config import BRAND_COLORS, get_rgba_fill, logger

class SpectrumPlotContainer:
    # Fixed on purpose: Plotly only resets the user's manual zoom/pan when this
    # value CHANGES between renders. Keeping it constant across every data update
    # means autozoom happens only via the user's own action (double-click on the
    # plot, or the toolbar's Autoscale/Reset-axes button) - never automatically.
    PLOT_UIREVISION = 'riid_spectrum_plot'
    # Same reasoning, applied to the new instantaneous count-rate plot (issue #34).
    CPS_PLOT_UIREVISION = 'riid_cps_plot'

    def __init__(self, service):
        self.service = service
        
        # ============ METRIC CARDS ROW (issue #37) ============
        # Replaces the old single "ID: ..." banner - the same information
        # (current status / detected isotopes) now lives in the first card,
        # alongside confidence, live time, and the active model name.
        with ui.row().classes('w-full gap-2'):
            self.metric_isotopes_val = self._build_metric_card('Detected Isotopes')
            self.metric_confidence_val = self._build_metric_card('Avg Confidence')
            self.metric_livetime_val = self._build_metric_card('Live Time')
            self.metric_model_val = self._build_metric_card('ML Model')
        self.metric_model_val.set_text(getattr(self.service, 'ml_model_name', 'UNKNOWN'))
        
        # ============ MAIN CONTENT: spectrum (left) + RIID results (right) ============
        # 65/35 split (was 50/50) - the spectrum reads better with more room,
        # while the results panel still has enough width for the class
        # probability bars and count-rate plot.
        with ui.row().classes('w-full gap-3 items-stretch no-wrap mt-2'):
            self.container = ui.column().classes('items-center justify-center rounded-lg border p-2 bg-white').style('width: 65%;')
            
            with ui.column().classes('gap-3').style('width: 35%;'):
                with ui.column().classes('w-full p-3 rounded-lg border bg-white gap-2').style('border-color: #E2E8F0;'):
                    ui.label('Class Probabilities (Multi-Label)').classes('text-xs font-bold uppercase tracking-wide text-zinc-700')
                    self.class_prob_container = ui.column().classes('w-full gap-2')
                
                # Issue #34: count-rate over time (distinct from the cumulative-average
                # CPS already shown in the spectrum plot's legend). Has its own Clear
                # button since it must NOT be wiped by the hysteresis cycle reset -
                # only an explicit operator action should clear this history.
                with ui.column().classes('w-full p-3 rounded-lg border bg-white gap-2 flex-1').style('border-color: #E2E8F0;'):
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Count-rate').classes('text-xs font-bold uppercase tracking-wide text-zinc-700')
                        ui.button('Clear', icon='delete_sweep', on_click=self.trigger_clear_cps_history) \
                            .props('dense flat size=sm').classes('text-[10px] text-zinc-500')
                    self.cps_plot_container = ui.column().classes('w-full')
        
        self._build_class_probability_bars()
        
        # Tracks the last state actually rendered into the spectrum plot, so the
        # heavy container.clear()+ui.plotly() redraw can be skipped when nothing is
        # actively being recorded and nothing has actually changed (issue #43).
        self._last_render_signature = None
        # The live spectrum ui.plotly widget, kept alive and updated in place
        # (rather than torn down and recreated) so the browser-side plot instance -
        # and the user's zoom/pan - persists. Reset to None only when falling back
        # to the standby splash (nothing to plot).
        self._plot_widget = None
        
        # Same pattern, for the new count-rate plot.
        self._last_cps_render_signature = None
        self._cps_plot_widget = None

    def _build_metric_card(self, label: str) -> ui.label:
        """Builds one of the top summary cards (issue #37) and returns its
        value label so callers can update it directly."""
        with ui.column().classes('flex-1 items-center justify-center p-3 rounded-lg border bg-white gap-0').style('border-color: #E2E8F0; min-width: 0;'):
            value_lbl = ui.label('--').classes('text-lg font-black text-center w-full').style('overflow-wrap: break-word; color: #374151;')
            ui.label(label.upper()).classes('text-[10px] text-zinc-500 uppercase tracking-wide text-center')
        return value_lbl

    def _build_class_probability_bars(self):
        """Pre-builds one row (name + percentage + progress bar) per class the
        active ML model can output, in the model's own label order - matches
        the screenshot's Background/Co-60/Cs-137/Eu-152/U-nat ordering for the
        multi-label model. Built once; update_ui_elements only updates values
        from here on, so this never needs a blink-prone teardown/rebuild."""
        self.class_prob_bars = {}
        labels = list(self.service.ml_inference.get_isotope_labels().values())
        with self.class_prob_container:
            for label in labels:
                with ui.column().classes('w-full gap-0'):
                    with ui.row().classes('w-full justify-between items-center no-wrap'):
                        ui.label(label).classes('text-[11px] font-medium text-zinc-700')
                        val_lbl = ui.label('0.0%').classes('text-[11px] font-bold text-zinc-500')
                    bar = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-2 rounded').props('color=grey-4')
                self.class_prob_bars[label] = (val_lbl, bar)

    def update_ui_elements(self):
        """Master orchestrator driving dynamic component layers stacking order and layout configurations."""
        self._update_metric_cards()
        self._update_class_probability_bars()
        self._update_count_rate_plot()
        
        spectrum_data = self.service.live_spectrum
        bg_data = self.service.background_spectrum
        current_state = self.service.state
        use_log = getattr(self.service, 'use_log_scale', True)
        
        is_actively_recording = current_state in ('ACQUIRING_SURVEY', 'BG_RECORDING')
        
        # Cheap fingerprint of everything that could visually change the plot. While
        # nothing is actively being recorded, only redraw if this actually differs
        # from the last render (e.g. STOP freezing the trace, CLEAR wiping it, the
        # log-scale toggle) instead of rebuilding the identical figure every tick.
        render_signature = (
            current_state,
            len(spectrum_data) if spectrum_data else 0,
            sum(spectrum_data) if spectrum_data else 0,
            len(bg_data) if bg_data else 0,
            sum(bg_data) if bg_data else 0,
            bool(use_log),
            bool(getattr(self.service, 'survey_stopped_with_data', False)),
        )
        
        if not is_actively_recording and render_signature == self._last_render_signature:
            return
        self._last_render_signature = render_signature
        
        # Guard: If no spectrum data is captured anywhere, draw the standby splash card
        if not spectrum_data and not bg_data:
            self.container.clear()
            self._plot_widget = None
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
        
        # 4. FIXED LAYER STACK: Append the environmental background trace SECOND to layer it on top
        peak_y_value = self._append_background_trace(
            plotly_traces, energy_axis, spectrum_data, bg_data, current_state, use_log, num_channels
        )
        
        # 5. Modular calculations: Determine the fluid vertical chart display constraints
        y_axis_layout = self._calculate_y_axis_layout(use_log, peak_y_value)

        fig = {
            'data': plotly_traces,
            'layout': {
                'xaxis': {'title': {'text': 'Energy (keV)', 'font': {'size': 10}}, 'automargin': True, 'tickfont': {'size': 8}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True},
                'yaxis': y_axis_layout,
                'margin': {'l': 55, 'r': 20, 't': 15, 'b': 45}, 
                'plot_bgcolor': BRAND_COLORS['plot_bg'], 
                'paper_bgcolor': BRAND_COLORS['plot_paper'], 
                'showlegend': True,
                'barmode': 'overlay',
                'legend': {'font': {'size': 8}, 'x': 0.70, 'y': 0.95, 'bgcolor': get_rgba_fill('legend_bg', alpha=0.7)},
                'uirevision': self.PLOT_UIREVISION,
            }
        }
        
        if self._plot_widget is None:
            # First time we have data to show (or coming back from the standby
            # splash) - build the widget fresh. From here on, subsequent updates
            # reuse this same instance instead of recreating it.
            self.container.clear()
            with self.container:
                self._plot_widget = ui.plotly(fig).classes('w-full h-[360px]')
        else:
            # Push new data into the existing widget via Plotly.react() under the
            # hood - this is what actually preserves the user's zoom/pan, since the
            # underlying graph DOM node is never torn down.
            self._plot_widget.figure = fig
            self._plot_widget.update()

    def _update_metric_cards(self):
        """Drives the four top summary cards from the service's latest state.
        "Detected Isotopes"/"Avg Confidence" come from self.service.last_ml_result
        (the FULL per-class breakdown, issue #37) when available; otherwise they
        fall back to the plain current_isotope_id status string (Standby,
        Accumulating, Recording Background, etc.) - the same text the old "ID: ..."
        banner used to show."""
        result = getattr(self.service, 'last_ml_result', None)
        threshold = getattr(self.service.ml_inference, 'CLASSIFICATION_THRESHOLD', 0.5)
        
        if result:
            # "Detected Isotopes" only lists actual isotopes, not the Background class.
            detected = {k: v for k, v in result.items() if k != 'Background' and v > threshold}
            if detected:
                self.metric_isotopes_val.set_text(' + '.join(detected.keys()))
                self.metric_isotopes_val.style('color: ' + BRAND_COLORS['crimson_trace'] + ';')
                avg_conf = sum(detected.values()) / len(detected)
                self.metric_confidence_val.set_text(f"{avg_conf * 100:.1f}%")
                self.metric_confidence_val.style('color: #059669;')
            else:
                bg_conf = result.get('Background', 0.0)
                self.metric_isotopes_val.set_text('Background')
                self.metric_isotopes_val.style('color: #374151;')
                self.metric_confidence_val.set_text(f"{bg_conf * 100:.1f}%")
                self.metric_confidence_val.style('color: #374151;')
        else:
            self.metric_isotopes_val.set_text(self.service.current_isotope_id)
            self.metric_isotopes_val.style('color: #374151;')
            self.metric_confidence_val.set_text('--')
            self.metric_confidence_val.style('color: #374151;')
        
        elapsed = getattr(self.service, 'survey_elapsed_seconds', 0)
        self.metric_livetime_val.set_text(f"{elapsed} s")

    def _update_class_probability_bars(self):
        """Updates the pre-built per-class bars from the latest full breakdown
        (issue #37). Bars for classes not in the current result (i.e. no
        inference has run yet, or the last attempt returned a plain status
        string) fall back to 0%."""
        result = getattr(self.service, 'last_ml_result', None) or {}
        threshold = getattr(self.service.ml_inference, 'CLASSIFICATION_THRESHOLD', 0.5)
        for label, (val_lbl, bar) in self.class_prob_bars.items():
            prob = float(result.get(label, 0.0) or 0.0)
            val_lbl.set_text(f"{prob * 100:.1f}%")
            bar.set_value(prob)
            bar.props(f"color={'red-6' if prob > threshold else 'grey-4'}")

    def _update_count_rate_plot(self):
        """Issue #34: renders the instantaneous count-rate-over-time plot from
        self.service.cps_history (a rolling window of (elapsed_s, cps, source)
        samples appended by both the survey AND background-recording polling
        loops). Samples are split by their source tag into two traces, colored
        to match the spectrum plot's own trace colors: blue (primary) for
        survey activity, gray (accent) for background recording activity -
        so the count-rate plot visually tracks whichever is currently running.
        Same persistent-widget/uirevision pattern as the main spectrum plot, so
        the operator's zoom/pan on this plot survives incoming data too."""
        history = list(getattr(self.service, 'cps_history', []) or [])
        current_state = self.service.state
        is_actively_sampling = current_state in ('ACQUIRING_SURVEY', 'BG_RECORDING')
        
        render_signature = (len(history), history[-1] if history else None, current_state)
        if not is_actively_sampling and render_signature == self._last_cps_render_signature:
            return
        self._last_cps_render_signature = render_signature
        
        if not history:
            self.cps_plot_container.clear()
            self._cps_plot_widget = None
            with self.cps_plot_container, ui.column().classes('w-full h-[140px] items-center justify-center text-zinc-400 gap-1'):
                ui.icon('show_chart', size='sm').style(f"color: {BRAND_COLORS['accent']};")
                ui.label('No data yet').classes('text-[11px] font-bold text-zinc-500')
            return
        
        # Split by source, preserving order (older entries are 2-tuples from
        # before this split existed - treated as 'survey' for backward compat).
        survey_x, survey_y, bg_x, bg_y = [], [], [], []
        for sample in history:
            x, y = sample[0], sample[1]
            source = sample[2] if len(sample) > 2 else 'survey'
            if source == 'bg':
                bg_x.append(x); bg_y.append(y)
            else:
                survey_x.append(x); survey_y.append(y)
        
        traces = []
        if bg_x:
            traces.append({
                'x': bg_x, 'y': bg_y, 'type': 'scatter', 'mode': 'lines', 'name': 'Background',
                'line': {'color': BRAND_COLORS['accent'], 'width': 1.5},
                'fill': 'tozeroy', 'fillcolor': get_rgba_fill('accent'),
            })
        if survey_x:
            traces.append({
                'x': survey_x, 'y': survey_y, 'type': 'scatter', 'mode': 'lines', 'name': 'Survey',
                'line': {'color': BRAND_COLORS['primary'], 'width': 1.5},
                'fill': 'tozeroy', 'fillcolor': get_rgba_fill('primary'),
            })
        
        fig = {
            'data': traces,
            'layout': {
                'xaxis': {'title': {'text': 'Time (s)', 'font': {'size': 10}}, 'automargin': True, 'tickfont': {'size': 8}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True},
                'yaxis': {'title': {'text': 'Count-rate (cps)', 'font': {'size': 10}}, 'automargin': True, 'tickfont': {'size': 8}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True, 'rangemode': 'tozero'},
                'margin': {'l': 50, 'r': 10, 't': 10, 'b': 40},
                'plot_bgcolor': BRAND_COLORS['plot_bg'], 'paper_bgcolor': BRAND_COLORS['plot_paper'],
                'showlegend': False,
                'uirevision': self.CPS_PLOT_UIREVISION,
            }
        }
        
        if self._cps_plot_widget is None:
            self.cps_plot_container.clear()
            with self.cps_plot_container:
                self._cps_plot_widget = ui.plotly(fig).classes('w-full h-[140px]')
        else:
            self._cps_plot_widget.figure = fig
            self._cps_plot_widget.update()

    def trigger_clear_cps_history(self):
        logger.warning("[USER_ACTION] Operator clicked Clear button on the Count-rate plot.")
        self.service.clear_cps_history()
        # Force an immediate redraw rather than waiting for the next tick, so the
        # plot visibly empties out right away.
        self._last_cps_render_signature = None
        self._update_count_rate_plot()

    def _get_energy_axis(self, num_channels: int) -> list:
        """Parses active hardware slope parameters and compiles keV coordinates."""
        prof = self.service.system.hw_profile
        a0 = float(prof.get('calib_a0') if prof.get('calib_a0') is not None else 0.0)
        a1 = float(prof.get('calib_a1') if prof.get('calib_a1') is not None else 1.0)
        a2 = float(prof.get('calib_a2') if prof.get('calib_a2') is not None else 0.0)
        return [a0 + (a1 * ch) + (a2 * (ch ** 2)) for ch in range(num_channels)]

    def _append_background_trace(self, traces: list, x_axis: list, spectrum_data: list, bg_data: list, state: str, use_log: bool, num_channels: int) -> float:
        """Calculates dynamic hardware-timed proportional background-scaling corrections and conditionally configures area shading layers."""
        peak_y = 0.0
        target_raw_y = None
        trace_name = "Environmental Background"
        
        if state == 'BG_RECORDING' and spectrum_data:
            target_raw_y = spectrum_data
            trace_name = "Recording Live Background..."
        elif bg_data and len(bg_data) == num_channels:
            bg_ms = float(getattr(self.service, 'bg_hardware_live_time_ms', 30000.0) or 30000.0)
            # Normalize whenever there's a survey elapsed-time to normalize against -
            # that includes the frozen "Last Survey (Stopped)" display, not just an
            # actively-running one. Previously this only checked ACQUIRING_SURVEY,
            # so pressing STOP silently fell back to the unscaled 300s-reference
            # background, producing a wildly mismatched amplitude against the still-
            # normalized-looking frozen survey trace right next to it.
            show_frozen_survey = getattr(self.service, 'survey_stopped_with_data', False)
            if state == 'ACQUIRING_SURVEY' or show_frozen_survey:
                survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
                time_scaling_factor = float(survey_ms / bg_ms)
                trace_name = f"Background (Normalized to {survey_ms/1000:.1f}s)"
            else:
                time_scaling_factor = 1.0
                trace_name = f"Background ({bg_ms/1000:.1f}s Reference)"
                
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
                'title': {'text': axis_title_string, 'font': {'size': 10}},
                'automargin': True,
                'type': 'log',
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
                'title': {'text': axis_title_string, 'font': {'size': 10}},
                'automargin': True,
                'type': 'linear',
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
                
                self.scale_checkbox = ui.checkbox(
                    'Log-scale', 
                    value=self.service.use_log_scale,
                    on_change=lambda e: self._toggle_plot_scale(e.value)
                ).classes('text-xs text-zinc-300 font-medium mt-1')

            with ui.column().classes('w-full p-3 bg-black border border-zinc-800 rounded-md gap-1 font-mono text-xs text-emerald-400'):
                self.status_lbl = ui.label('SYSTEM: Syncing...')
                self.bg_status_lbl = ui.label('BACKGROUND: Missing Profile')

            # ============ BACKGROUND SPECTRUM (collapsible) ============
            # Recording/loading/storing a background is a secondary, occasional
            # workflow compared to running a live survey - grouping it into a
            # single collapsed-by-default panel keeps it one click away without
            # competing for attention with the always-visible Live Survey
            # controls below. Auto-expands while a capture is actively running
            # (see refresh_widget_states) so its progress bar stays visible.
            with ui.expansion('Background Spectrum', icon='security', value=False) \
                    .classes('w-full bg-zinc-800 border border-zinc-700 rounded-md') \
                    .props('dense expand-separator header-class="text-xs font-bold text-zinc-300"') as self.bg_expansion:
                with ui.column().classes('w-full gap-2 p-2'):
                    self.bg_time_input = ui.number('BG Record Time (s)', value=self.service.bg_target_time, format='%d').classes('w-full text-xs text-white').props('dark dense outlined')

                    self.bg_progress_bar = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-1.5 rounded transition-all').props('color=amber')
                    self.bg_progress_bar.set_visibility(False)

                    self.bg_btn = ui.button('RECORD BACKGROUND SPECTRUM', icon='security', on_click=self.trigger_bg)
                    self.bg_btn.style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").props('dense').classes('w-full py-2 text-xs shadow-md')

                    ui.separator().classes('bg-zinc-700')

                    # Issue #44: lets the operator load an already-saved background
                    # (see issue #45) instead of recording a fresh one. Purely
                    # additive - the RECORD flow above is completely untouched.
                    with ui.column().classes('w-full gap-1') as self.load_bg_group:
                        with ui.row().classes('w-full gap-2 items-end'):
                            self.bg_file_select = ui.select(options=[], label='Load Pre-Recorded Background').props('dense outlined dark').classes('flex-1 text-xs')
                            ui.button(icon='refresh', on_click=self.refresh_bg_file_list).props('dense flat round').classes('text-zinc-300')
                        self.load_bg_btn = ui.button('LOAD SELECTED BACKGROUND', icon='folder_open', on_click=self.trigger_load_bg)
                        self.load_bg_btn.style(f"background-color: {BRAND_COLORS['secondary']}; border: 1px solid #4A5568; color: #FFFFFF;").props('dense').classes('w-full py-1.5 text-xs')
                    self.refresh_bg_file_list()

                    ui.separator().classes('bg-zinc-700')

                    # Issue #45: lets the operator persist the latest recorded
                    # background spectrum to disk (data/spectra/background/),
                    # independent of any survey/batch activity. Hidden while a NEW
                    # background capture is in progress to avoid ambiguity about
                    # which background would be saved.
                    self._build_save_bg_modal()
                    self.save_bg_btn = ui.button('Store Background Spectrum', icon='save', on_click=self.open_save_bg_dialog)
                    self.save_bg_btn.style(f"background-color: {BRAND_COLORS['secondary']}; border: 1px solid #4A5568; color: #FFFFFF;").props('dense').classes('w-full py-1.5 text-xs')

            # ============ LIVE SURVEY (always visible - primary workflow) ============
            ui.label('Live Survey').classes('text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1')
            with ui.row().classes('w-full gap-2 no-wrap pt-1'):
                self.play_stop_btn = ui.button('START', icon='play_arrow', on_click=self.trigger_play_stop_toggle)
                self.play_stop_btn.style("background-color: #10B981; font-weight: bold;").props('dense').classes('flex-1 py-1.5')
                self.clear_btn = ui.button('CLEAR', icon='delete_sweep', on_click=self.trigger_clear)
                self.clear_btn.style(f"background-color: {BRAND_COLORS['secondary']}; border: 1px solid #4A5568;").props('dense').classes('flex-1 py-1.5')

            # Issue #41: bundles the last spectrum shown here with the current
            # background into a downloadable .zip (both in .json and .spe).
            # Visible only once a background has settled (see refresh_widget_states).
            self.download_riid_btn = ui.button('Download Spectrum', icon='download', on_click=self.trigger_download_riid)
            self.download_riid_btn.style(f"background-color: {BRAND_COLORS['primary']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('w-full mt-1 py-1.5 text-xs')

    def _toggle_plot_scale(self, value: bool):
        logger.info(f"[USER_ACTION] Operator modified counts scaling preference selection -> use_log_scale={value}")
        self.service.use_log_scale = value

    def trigger_bg(self):
        logger.warning(f"[USER_ACTION] Operator clicked RECORD BACKGROUND SPECTRUM button. Duration: {self.bg_time_input.value}s")
        self.service.start_background_recording(int(self.bg_time_input.value or 30))

    def refresh_bg_file_list(self):
        """Repopulates the load-background dropdown from whatever's currently
        in data/spectra/background/ (via the service, which owns that path)."""
        files = self.service.list_available_background_files()
        self.bg_file_select.options = files
        self.bg_file_select.update()

    def trigger_load_bg(self):
        filename = self.bg_file_select.value
        logger.warning(f"[USER_ACTION] Operator clicked LOAD SELECTED BACKGROUND button. File: {filename}")
        ok, msg = self.service.load_background_spectrum(filename)
        if ok:
            # A returned message containing a calibration mismatch is still a
            # successful load, just one the operator should be aware of.
            ui.notify(msg, type="warning" if "differs" in msg else "positive")
        else:
            ui.notify(msg, type="negative")

    def _build_save_bg_modal(self):
        """Prompt dialog for issue #45, requirement 5: asks for a file name
        (timestamp-prefixed suggestion) and two checkboxes for output format,
        both checked by default, with at least one required."""
        with ui.dialog() as self.save_bg_dialog, ui.card().classes('p-4 w-96 space-y-3'):
            ui.label('Store Background Spectrum').classes('text-sm font-bold text-blue-600')

            self.bg_filename_input = ui.input('File Name').props('dense outlined').classes('w-full text-xs')

            ui.label('Output Format').classes('text-xs font-bold text-zinc-600 mt-1')
            with ui.row().classes('w-full gap-4'):
                self.bg_save_json_cb = ui.checkbox('JSON', value=True).classes('text-xs')
                self.bg_save_spe_cb = ui.checkbox('SPE', value=True).classes('text-xs')

            def commit_save():
                if not self.bg_save_json_cb.value and not self.bg_save_spe_cb.value:
                    ui.notify("Select at least one output format (JSON and/or SPE).", type="negative")
                    return
                ok, msg = self.service.save_background_spectrum(
                    self.bg_filename_input.value,
                    save_json=self.bg_save_json_cb.value,
                    save_spe=self.bg_save_spe_cb.value
                )
                if ok:
                    logger.warning(f"[USER_ACTION] Operator saved background spectrum: {msg}")
                    ui.notify(msg, type="positive")
                    self.refresh_bg_file_list()
                    self.save_bg_dialog.close()
                else:
                    ui.notify(msg, type="negative")

            with ui.row().classes('w-full gap-2 pt-1'):
                ui.button('Cancel', on_click=self.save_bg_dialog.close).props('dense outline').classes('flex-1')
                ui.button('Save', icon='save', on_click=commit_save).props('dense color=primary').classes('flex-1')

    def open_save_bg_dialog(self):
        # Re-suggest a fresh timestamp prefix every time the dialog is opened,
        # rather than leaving a stale one from a previous save attempt.
        self.bg_filename_input.set_value(f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_background")
        self.save_bg_dialog.open()

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

    def trigger_download_riid(self):
        logger.warning("[USER_ACTION] Operator clicked Download Spectrum button.")
        ok, msg, zip_bytes, base_filename = self.service.build_riid_download_zip()
        if not ok:
            ui.notify(msg, type="negative")
            return
        ui.notify(msg, type="positive")
        ui.download(zip_bytes, f"{base_filename}_bundle.zip", media_type='application/zip')

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
            self.bg_status_lbl.set_text("BACKGROUND SPECTRUM: CALIBRATED (READY)")
            self.bg_status_lbl.style("color: #34D399;")
        else:
            self.bg_status_lbl.set_text("BACKGROUND SPECTRUM: ABSENT (LOCKED)")
            self.bg_status_lbl.style("color: #F87171;")

        # Hide the entire panel during a live survey - simpler than showing the
        # BG collection time as a disabled field. Visible in every other state
        # (idle, an active BG capture, or batch recording).
        self.bg_expansion.set_visibility(not is_survey_running)

        # The Background Spectrum panel's action buttons (Record/Load/Store) are
        # already hidden below whenever the app isn't idle. The BG Record Time
        # field itself needs the same gate: it must stay visible whenever the
        # panel itself is (so the operator can see the value that was actually
        # used) but only be editable while idle - this includes during
        # BG_RECORDING itself, where it must reflect the duration already
        # committed to the running capture, not something that can be changed
        # mid-capture.
        if is_idle:
            self.bg_time_input.enable()
        else:
            self.bg_time_input.disable()

        if is_bg_running:
            # Auto-open the collapsed panel so the operator sees progress without
            # needing to manually expand it mid-capture.
            self.bg_expansion.value = True
            self.bg_progress_bar.set_visibility(True)
            prog_val = getattr(self.service, 'bg_progress', 0.0)
            self.bg_progress_bar.set_value(prog_val)
        else:
            self.bg_progress_bar.set_visibility(False)
            self.bg_progress_bar.set_value(0.0)

        self.bg_btn.set_visibility(is_idle and hw_ok)

        # Issue #44: loading a pre-recorded background is only meaningful while
        # idle (matches the backend's own state guard in load_background_spectrum).
        self.load_bg_group.set_visibility(is_idle)

        # Issue #45: only offer saving when there's actually a background to
        # save, and only while fully idle - not during a new BG capture (which
        # background would get written is ambiguous), and not during an active
        # survey (keeps this control's visibility consistent with the
        # load-background picker just above, and avoids saving mid-run).
        self.save_bg_btn.set_visibility(has_bg and is_idle)

        # Issue #41: visible once the background has "settled" - it exists and
        # isn't currently being (re)captured. Unlike save_bg_btn above, this
        # stays visible during an active survey too, since downloading the
        # in-progress/last-shown RIID spectrum together with the background is
        # exactly the point of this button.
        self.download_riid_btn.set_visibility(has_bg and not is_bg_running)

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