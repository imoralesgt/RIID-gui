"""The Spectrum ID tab: live spectrum/count-rate plots and operator controls.

:class:`SpectrumPlotContainer` renders the live spectrum and count-rate-over-
time Plotly charts, the RIID summary metric cards, and the class-probability
bars. :class:`ControlPanelSidebar` renders the adjacent operator controls
(model switch, visualization mode, thresholds, background record/load/save,
survey start/stop). Both are backed by the shared ``RIIDCoreService``
instance and together make up the "Spectrum ID" tab built in ``main.py``.
"""

import os
import json
import math
from datetime import datetime, timezone
from nicegui import ui
from config import BRAND_COLORS, get_rgba_fill, logger

class SpectrumPlotContainer:
    """Renders the live/count-rate plots, metric cards, and probability bars."""

    # Fixed on purpose: Plotly only resets the user's manual zoom/pan when this
    # value CHANGES between renders. Keeping it constant across every data update
    # means autozoom happens only via the user's own action (double-click on the
    # plot, or the toolbar's Autoscale/Reset-axes button) - never automatically.
    PLOT_UIREVISION = 'riid_spectrum_plot'
    # Same reasoning, applied to the new instantaneous count-rate plot.
    CPS_PLOT_UIREVISION = 'riid_cps_plot'

    def __init__(self, service):
        """Builds the plot container's widgets and wires them to `service`.

        Args:
            service (RIIDCoreService): The shared backend service instance
                this container reads spectrum/state data from.
        """
        self.service = service
        
        # ============ METRIC CARDS ROW ============
        # Current status / detected isotopes lives in the first card,
        # alongside confidence, live time, and the active model name.
        with ui.row().classes('w-full gap-2 riid-metric-cards-row'):
            self.metric_isotopes_val = self._build_metric_card('Detected Isotopes')
            self.metric_confidence_val = self._build_metric_card('Avg Confidence')
            self.metric_livetime_val = self._build_metric_card('Live Time')
            # Was a static label, now a live model-switcher. Enabled
            # only while idle (see update_ui_elements) - switching models
            # mid-survey would produce a confusing mix of old/new-model results.
            with ui.column().classes('flex-1 items-center justify-center p-2 rounded-lg border bg-white gap-0 riid-metric-card').style('border-color: #E2E8F0; min-width: 0; height: 64px;'):
                self.model_select = ui.select(
                    {'cnn_multilabel': 'cnn_multilabel', 'cnn_deep': 'cnn_deep'},
                    value=getattr(self.service, 'ml_model_name', 'cnn_multilabel'),
                    on_change=self.trigger_model_change
                ).props('dense borderless options-dense hide-bottom-space').classes('text-center font-black text-lg riid-metric-value').style('min-width: 0; margin: 0; line-height: 1.2;')
                ui.label('ML MODEL').classes('text-[10px] text-zinc-500 uppercase tracking-wide text-center')
        
        # ============ MAIN CONTENT: spectrum (left) + RIID results (right) ============
        # 65/35 split (was 50/50) - the spectrum reads better with more room,
        # while the results panel still has enough width for the class
        # probability bars and count-rate plot.
        with ui.row().classes('w-full gap-3 items-stretch no-wrap mt-2 riid-spectrum-split-row'):
            with ui.column().classes('rounded-lg border bg-white p-2 gap-1').style('width: 65%; border-color: #E2E8F0;'):
                with ui.row().classes('w-full justify-between items-center px-1 flex-wrap'):
                    self.spectrum_card_title = ui.label('Live spectrum').classes('text-xs font-bold uppercase tracking-wide text-zinc-700')
                    with ui.row().classes('items-center gap-3'):
                        # Lets the operator choose between the two
                        # visualization templates - overlaid background+spectrum
                        # traces (the existing default), or a
                        # single background-subtracted spectrum trace. Two separate
                        # buttons rather than a single ui.toggle, since each option
                        # needs to show its own trace's color when active (blue for
                        # the overlay mode, the new subtracted-trace orange for the
                        # other) - Quasar's toggle component only supports one
                        # uniform "selected" color across all its options.
                        with ui.row().classes('items-center gap-1'):
                            self.viz_mode_btn_overlay = ui.button('Background & Spectrum', on_click=lambda: self.trigger_viz_mode_change('overlay')) \
                                .props('dense no-caps unelevated size=sm').classes('text-[10px]')
                            self.viz_mode_btn_subtracted = ui.button('Spectrum - Background', on_click=lambda: self.trigger_viz_mode_change('subtracted')) \
                                .props('dense no-caps unelevated size=sm').classes('text-[10px]')
                        # Small control here, next to the plot it affects, matching
                        # the Count-rate card's Clear button placement.
                        self.scale_checkbox = ui.checkbox(
                            'Log-scale', value=getattr(self.service, 'use_log_scale', False),
                            on_change=self.trigger_log_scale_change
                        ).classes('text-xs text-zinc-600 font-medium')
                self.container = ui.column().classes('items-center justify-center w-full')
            
            with ui.column().classes('gap-3').style('width: 35%;'):
                with ui.column().classes('w-full p-3 rounded-lg border bg-white gap-2').style('border-color: #E2E8F0;'):
                    ui.label('Class Probabilities (Multi-Label)').classes('text-xs font-bold uppercase tracking-wide text-zinc-700')
                    self.class_prob_container = ui.column().classes('w-full gap-2')
                
                # Count-rate over time (distinct from the cumulative-average
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
        
        # 'Overlay' (background+spectrum, both traces) or
        # 'subtracted' (single background-subtracted spectrum trace) - set by
        # the two buttons above, read by update_ui_elements to pick which
        # trace(s) to build.
        self.viz_mode = 'overlay'
        self._update_viz_mode_buttons()
        
        # Tracks the last state actually rendered into the spectrum plot, so the
        # heavy container.clear()+ui.plotly() redraw can be skipped when nothing is
        # actively being recorded and nothing has actually changed.
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
        """Builds one of the top summary cards and returns its value label so
        callers can update it directly. Fixed height so all four cards in
        the row - including the ML Model select, which has its own internal
        Quasar sizing quirks - line up uniformly regardless of what each
        one's content naturally wants."""
        with ui.column().classes('flex-1 items-center justify-center p-2 rounded-lg border bg-white gap-0 riid-metric-card').style('border-color: #E2E8F0; min-width: 0; height: 64px;'):
            value_lbl = ui.label('--').classes('text-lg font-black text-center w-full riid-metric-value').style('overflow-wrap: break-word; color: #374151; line-height: 1.2;')
            ui.label(label.upper()).classes('text-[10px] text-zinc-500 uppercase tracking-wide text-center')
        return value_lbl

    def _build_class_probability_bars(self):
        """(Re)builds one row (name + percentage + progress bar) per class the
        active ML model can output, in the model's own label order - matches
        the reference screenshot's Background/Co-60/Cs-137/Eu-152/U-nat
        ordering for the multilabel model. Called once at construction, and
        again by trigger_model_change whenever the operator
        switches models - cnn_deep and cnn_multilabel have different label
        sets (8 vs 5 classes), so the bars can't just be updated in place."""
        self.class_prob_bars = {}
        self.class_prob_container.clear()
        labels = list(self.service.ml_inference.get_isotope_labels().values())
        with self.class_prob_container:
            for label in labels:
                with ui.column().classes('w-full gap-0'):
                    with ui.row().classes('w-full justify-between items-center no-wrap'):
                        ui.label(label).classes('text-[11px] font-medium text-zinc-700')
                        val_lbl = ui.label('0.0%').classes('text-[11px] font-bold text-zinc-500')
                    bar = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-2 rounded').props('color=grey-4')
                self.class_prob_bars[label] = (val_lbl, bar)

    def trigger_model_change(self, e):
        """Switches the active ML model. Rebuilds the class
        probability bars for the new model's label set on success, or reverts
        the dropdown to whatever's actually active if the switch failed."""
        new_model = e.value
        logger.warning(f"[USER_ACTION] Operator changed ML model selection to '{new_model}'.")
        ok, msg = self.service.set_ml_model(new_model)
        if ok:
            ui.notify(msg, type="positive")
            self._build_class_probability_bars()
        else:
            ui.notify(msg, type="negative")
            self.model_select.set_value(self.service.ml_model_name)

    def trigger_viz_mode_change(self, mode: str):
        """Switches between the two spectrum visualization
        templates - 'overlay' (background+spectrum, both traces) or
        'subtracted' (single background-subtracted trace)."""
        logger.info(f"[USER_ACTION] Operator changed spectrum visualization mode -> {mode}")
        self.viz_mode = mode
        self._update_viz_mode_buttons()
        self._last_render_signature = None  # force an immediate redraw
        self.update_ui_elements()

    def _update_viz_mode_buttons(self):
        """Colors the active visualization-mode button to match its own
        trace's color (blue for overlay, orange for subtracted - see
        BRAND_COLORS['subtracted_trace']), and the inactive one as a plain
        outline, so the selector visually previews what's about to be shown.
        Also updates the card's own title to reflect the active mode."""
        active_style = "color: #FFFFFF !important; font-weight: bold; border: none;"
        inactive_style = "background-color: #FFFFFF !important; color: #4B5563 !important; border: 1px solid #D1D5DB !important; font-weight: normal;"
        
        if self.viz_mode == 'overlay':
            self.viz_mode_btn_overlay.style(f"background-color: {BRAND_COLORS['primary']} !important; {active_style}")
            self.viz_mode_btn_subtracted.style(inactive_style)
            self.spectrum_card_title.set_text('Live spectrum')
        else:
            self.viz_mode_btn_overlay.style(inactive_style)
            self.viz_mode_btn_subtracted.style(f"background-color: {BRAND_COLORS['subtracted_trace']} !important; {active_style}")
            self.spectrum_card_title.set_text('Live spectrum (background subtracted)')

    def trigger_log_scale_change(self, e):
        """Toggles the live spectrum plot between linear and log count scale."""
        logger.info(f"[USER_ACTION] Operator modified counts scaling preference selection -> use_log_scale={e.value}")
        self.service.use_log_scale = e.value
        self._last_render_signature = None  # force an immediate redraw

    def update_ui_elements(self):
        """Master orchestrator driving dynamic component layers stacking order and layout configurations."""
        self._update_metric_cards()
        self._update_class_probability_bars()
        self._update_count_rate_plot()
        
        spectrum_data = self.service.live_spectrum
        bg_data = self.service.background_spectrum
        current_state = self.service.state
        use_log = getattr(self.service, 'use_log_scale', False)
        
        # Model switching is only meaningful while idle - switching
        # mid-survey would produce a confusing mix of old/new-model results.
        if current_state == 'IDLE':
            self.model_select.enable()
        else:
            self.model_select.disable()
        
        # The subtracted-mode button is only meaningful when there's an actual
        # live survey trace to subtract from - exactly the same condition
        # _append_subtracted_trace itself checks before drawing anything.
        # Disabled during BG_RECORDING (only the background is being captured)
        # and during plain idle with no survey ever run/stopped (only the
        # background is being shown in that case too). Checked here, early,
        # so it's never skipped by the render-signature cache below.
        show_frozen_survey_early = getattr(self.service, 'survey_stopped_with_data', False)
        subtracted_mode_available = current_state == 'ACQUIRING_SURVEY' or show_frozen_survey_early
        if subtracted_mode_available:
            self.viz_mode_btn_subtracted.enable()
        else:
            self.viz_mode_btn_subtracted.disable()
            # Don't leave the operator stranded on a mode that would now show
            # a blank plot - fall back to the always-available overlay mode.
            # Mutates state directly rather than calling trigger_viz_mode_change()
            # (which would itself call update_ui_elements() again, re-entrantly,
            # since we're already inside that same method call) - the rest of
            # this call picks up the updated viz_mode naturally further down.
            if self.viz_mode == 'subtracted':
                self.viz_mode = 'overlay'
                self._update_viz_mode_buttons()
                self._last_render_signature = None
        
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
            self.viz_mode,
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
        cps_raw_value = 0.0
        if (current_state == 'ACQUIRING_SURVEY' or show_frozen_survey) and spectrum_data:
            total_cts = sum(spectrum_data)
            survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
            survey_secs = float(survey_ms / 1000.0)
            if survey_secs > 0.0:
                cps_raw_value = float(total_cts / survey_secs)

        # Initialize trace list matrix
        plotly_traces = []
        peak_y_value = 0.0
        
        if current_state == 'BG_RECORDING':
            # Background capture in progress - always show its own live preview,
            # regardless of the operator's overlay/subtracted preference (that
            # choice only applies to the survey visualization, not to recording
            # a fresh background).
            peak_y_value = self._append_background_trace(
                plotly_traces, energy_axis, spectrum_data, bg_data, current_state, use_log, num_channels
            )
        elif self.viz_mode == 'subtracted':
            # Visualization template 2: single background-subtracted trace.
            peak_y_value = self._append_subtracted_trace(
                plotly_traces, energy_axis, spectrum_data, bg_data, current_state, use_log, num_channels, cps_raw_value
            )
        else:
            # Visualization template 1 (default): both traces overlaid. Append
            # order fixes the Plotly z-order (later traces draw on top), so the
            # live survey trace is added first (bottom layer) and the
            # background trace second (drawn on top of it).
            peak_y_value = self._append_live_survey_trace(
                plotly_traces, energy_axis, spectrum_data, current_state, use_log, peak_y_value, num_channels, cps_raw_value
            )
            peak_y_value = self._append_background_trace(
                plotly_traces, energy_axis, spectrum_data, bg_data, current_state, use_log, num_channels
            )
        
        # 5. Modular calculations: Determine the fluid vertical chart display constraints
        y_axis_layout = self._calculate_y_axis_layout(use_log, peak_y_value)

        fig = {
            'data': plotly_traces,
            'layout': {
                'xaxis': {'title': {'text': 'Energy (keV)', 'font': {'size': 13}}, 'automargin': True, 'tickfont': {'size': 11}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True},
                'yaxis': y_axis_layout,
                'margin': {'l': 55, 'r': 20, 't': 15, 'b': 45}, 
                'plot_bgcolor': BRAND_COLORS['plot_bg'], 
                'paper_bgcolor': BRAND_COLORS['plot_paper'], 
                'showlegend': True,
                'barmode': 'overlay',
                'legend': {'font': {'size': 11}, 'x': 0.98, 'xanchor': 'right', 'y': 0.95, 'bgcolor': get_rgba_fill('legend_bg', alpha=0.7)},
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
        (the FULL per-class breakdown) when available; otherwise they fall
        back to the plain current_isotope_id status string (Standby,
        Accumulating, Recording Background, etc.)."""
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
        """Updates the pre-built per-class bars from the latest full
        breakdown. Bars for classes not in the current result (i.e. no
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
        """Renders the instantaneous count-rate-over-time plot from
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
                'xaxis': {'title': {'text': 'Time (s)', 'font': {'size': 13}}, 'automargin': True, 'tickfont': {'size': 11}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True},
                'yaxis': {'title': {'text': 'Count-rate (cps)', 'font': {'size': 13}}, 'automargin': True, 'tickfont': {'size': 11}, 'gridcolor': BRAND_COLORS['plot_grid'], 'autorange': True, 'rangemode': 'tozero'},
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
        """Clears the count-rate plot's history and forces an immediate redraw."""
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

    def _compute_normalized_background(self, bg_data: list, state: str, num_channels: int) -> tuple:
        """Shared background time-normalization: scales the
        background spectrum's counts proportionally to match the current
        survey's elapsed time - or reports it at its own raw reference
        duration when there's no survey elapsed-time to normalize against
        (e.g. fully idle with no survey ever run) - including a frozen survey
        (stopped with data still showing, see survey_stopped_with_data),
        which still needs a valid elapsed time to normalize against. Used by
        both the overlay mode's separate background trace and the subtracted
        mode's single trace, so this normalization math only has to live in
        one place.
        
        Returns:
            (list | None, str): (scaled background counts matching
            num_channels, or None if unavailable/length-mismatched; the
            complete, ready-to-use trace name).
        """
        if not bg_data or len(bg_data) != num_channels:
            return None, "Environmental Background"
        
        default_bg_ms = self.service.DEFAULT_BG_TARGET_TIME_S * 1000
        bg_ms = float(getattr(self.service, 'bg_hardware_live_time_ms', default_bg_ms) or default_bg_ms)
        # Normalize whenever there's a survey elapsed-time to normalize against -
        # that includes the frozen "Last Survey (Stopped)" display, not just an
        # actively-running one.
        show_frozen_survey = getattr(self.service, 'survey_stopped_with_data', False)
        if state == 'ACQUIRING_SURVEY' or show_frozen_survey:
            survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
            time_scaling_factor = float(survey_ms / bg_ms)
            # Deliberately drops the "(Normalized to Xs)" duration
            # detail - the operator already sees the survey's live time via
            # the other indicators (the LIVE TIME metric card, OP_STATE line).
            label = "Normalized background"
        else:
            time_scaling_factor = 1.0
            label = "Background"
        
        return [float(counts * time_scaling_factor) for counts in bg_data], label

    def _append_background_trace(self, traces: list, x_axis: list, spectrum_data: list, bg_data: list, state: str, use_log: bool, num_channels: int) -> float:
        """Calculates dynamic hardware-timed proportional background-scaling corrections and conditionally configures area shading layers."""
        peak_y = 0.0
        target_raw_y = None
        trace_name = "Environmental Background"
        
        if state == 'BG_RECORDING' and spectrum_data:
            target_raw_y = spectrum_data
            trace_name = "Recording Live Background..."
        else:
            scaled_bg, label = self._compute_normalized_background(bg_data, state, num_channels)
            if scaled_bg is not None:
                target_raw_y = scaled_bg
                trace_name = label  # already the complete, ready-to-use trace name

        if target_raw_y is not None and len(target_raw_y) == num_channels:
            peak_y = float(max(target_raw_y)) if target_raw_y else 0.0
            processed_bg_y = [v if v >= 1 else 1 for v in target_raw_y] if use_log else target_raw_y
            
            if use_log:
                # No area shading in log scale - filling to y=0 on a log axis
                # is misleading, since the visual "zero" floor is actually the
                # flooring clip above, not a true zero.
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

    @staticmethod
    def _format_cps(value: float) -> str:
        """Formats a count-rate for the live-survey / live-survey-minus-
        background spectrum plot legends: 'cps' below 1000, 'kcps' at or
        above 1000, always showing exactly 4 significant digits regardless of
        magnitude (e.g. 79.83 cps, 5.456 cps, 1.235 kcps, 12.35 kcps).
        
        Does NOT use Python's '%.4g' format directly - for values >= 10000 that
        would switch to scientific notation (e.g. '1.235e+04'), which isn't
        wanted here. Computing the decimal count explicitly from the value's
        own magnitude keeps the output as a plain, fixed-point number in
        every case.
        """
        value = max(0.0, float(value))

        def sig_figs(v: float) -> str:
            """Formats `v` to 4 significant figures as a fixed-point string."""
            if v == 0:
                return "0.000"
            magnitude = int(math.floor(math.log10(abs(v)))) + 1
            decimals = max(0, 4 - magnitude)
            formatted = f"{v:.{decimals}f}"
            # Rounding can push the value up a full order of magnitude (e.g.
            # 999.96 at 1 decimal -> "1000.0", or 0.99996 at 4 decimals ->
            # "1.0000") - that leaves one extra digit, so redo with one fewer
            # decimal to keep exactly 4 significant figures.
            rounded = float(formatted)
            new_magnitude = int(math.floor(math.log10(abs(rounded)))) + 1 if rounded != 0 else magnitude
            if new_magnitude > magnitude:
                decimals = max(0, decimals - 1)
                formatted = f"{v:.{decimals}f}"
            return formatted

        if value >= 1000:
            return f"{sig_figs(value / 1000.0)} kcps"

        formatted = sig_figs(value)
        # Edge case: rounding up (e.g. 999.96 -> "1000.0") can push the
        # displayed value across the kcps threshold even though the raw value
        # was just under it - recheck against the ROUNDED value so the unit
        # shown always matches what's actually displayed.
        if float(formatted) >= 1000:
            return f"{sig_figs(value / 1000.0)} kcps"
        return f"{formatted} cps"

    def _append_live_survey_trace(self, traces: list, x_axis: list, spectrum_data: list, state: str, use_log: bool, current_peak_y: float, num_channels: int, cps_value: float) -> float:
        """Applies safe log filters and overlays the main active survey line with integrated label CPS readouts and scale-dependent shading."""
        peak_y = current_peak_y
        
        if spectrum_data and len(spectrum_data) == num_channels and sum(spectrum_data) > 0 and \
           (state == 'ACQUIRING_SURVEY' or getattr(self.service, 'survey_stopped_with_data', False)):
            live_max = float(max(spectrum_data))
            if live_max > peak_y:
                peak_y = live_max
                
            processed_live_y = [val if val >= 1 else 1 for val in spectrum_data] if use_log else spectrum_data
            
            # Dynamically embed the current CPS metrics straight into the plot trace name label string
            if state == 'ACQUIRING_SURVEY':
                legend_label_name = f"Live Survey ({self._format_cps(cps_value)})"
            else:
                legend_label_name = f"Last Survey (Stopped, {self._format_cps(cps_value)})"
            
            if use_log:
                # No area shading fill in log scale - see the background
                # trace's log-mode branch above for why.
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
                # Pale transparent blue area-under-the-curve shade, generated
                # from the centralized primary color hex key.
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

    def _append_subtracted_trace(self, traces: list, x_axis: list, spectrum_data: list, bg_data: list, state: str, use_log: bool, num_channels: int, cps_value: float) -> float:
        """Visualization template 2: a single trace showing the live
        spectrum with the background subtracted out, matching the 
        app's "Spectrum with subtracted background" template - as opposed to
        the default 'overlay' mode, which shows both traces separately on top
        of each other.
        
        The actual subtraction is delegated to
        RIIDCoreService.compute_background_subtracted_spectrum(), which reuses
        MLPreprocessing.subtract_background() - the exact same step
        MlInference.inference_pipeline() runs before feeding a spectrum to the
        model - rather than maintaining a second, separate implementation
        here that could silently drift out of sync with what the classifier
        itself actually reasons over."""
        peak_y = 0.0
        if not (spectrum_data and len(spectrum_data) == num_channels):
            return peak_y
        if not (state == 'ACQUIRING_SURVEY' or getattr(self.service, 'survey_stopped_with_data', False)):
            return peak_y
        
        survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
        default_bg_ms = self.service.DEFAULT_BG_TARGET_TIME_S * 1000
        bg_ms = float(getattr(self.service, 'bg_hardware_live_time_ms', default_bg_ms) or default_bg_ms)
        
        subtracted = self.service.compute_background_subtracted_spectrum(
            spectrum_data=spectrum_data, spectrum_live_time_s=survey_ms / 1000.0,
            bg_data=bg_data, bg_live_time_s=bg_ms / 1000.0
        )
        
        has_background = bool(bg_data) and len(bg_data) > 0
        if has_background:
            # The legend's count-rate is the NET
            # (subtracted) rate - total count-rate minus the background's own
            # rate - not the raw total rate (which is what cps_value, passed
            # in from update_ui_elements, represents and is used for the
            # overlay mode's "Live Survey" label instead). Clipped to >= 0:
            # with few counts (e.g. early in a survey), statistical noise can
            # momentarily make the background's own rate exceed the survey's,
            # which would otherwise show a nonsensical negative count-rate.
            survey_secs = survey_ms / 1000.0
            bg_secs = bg_ms / 1000.0
            raw_cps = float(sum(spectrum_data)) / survey_secs if survey_secs > 0 else 0.0
            bg_cps = float(sum(bg_data)) / bg_secs if bg_secs > 0 else 0.0
            net_cps = max(0.0, raw_cps - bg_cps)
            trace_name = f"Live survey, no bkg. ({self._format_cps(net_cps)})"
        else:
            # subtract_background() itself falls back to the raw spectrum when
            # there's nothing usable to subtract - name the trace accordingly.
            trace_name = f"Live Survey Session ({self._format_cps(cps_value)}) - no background to subtract"
        
        peak_y = float(max(subtracted)) if subtracted else 0.0
        processed_y = [v if v >= 1 else 1 for v in subtracted] if use_log else subtracted
        
        trace = {
            'x': x_axis, 'y': processed_y, 'type': 'scatter', 'mode': 'lines',
            'name': trace_name,
            'line': {'color': BRAND_COLORS['subtracted_trace'], 'width': 1.8},
        }
        if not use_log:
            trace['fill'] = 'tozeroy'
            trace['fillcolor'] = get_rgba_fill('subtracted_trace')
        traces.append(trace)
        
        return peak_y

    def _calculate_y_axis_layout(self, use_log: bool, peak_y_value: float) -> dict:
        """Configures a pure native Plotly auto-scaling layout box format preventing integer compression."""
        axis_title_string = 'Counts'
        
        if use_log:
            # Bypasses manual calculation limits. Leverages native Plotly autorange tracking 
            # while binding strict formatting rules to force base-10 power of ten index grid lines.
            return {
                'title': {'text': axis_title_string, 'font': {'size': 13}},
                'automargin': True,
                'type': 'log',
                'tickfont': {'size': 11},
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
                'title': {'text': axis_title_string, 'font': {'size': 13}},
                'automargin': True,
                'type': 'linear',
                'tickfont': {'size': 11},
                'gridcolor': BRAND_COLORS['plot_grid'],
                'autorange': True
            }


class ControlPanelSidebar:
    """The Spectrum ID tab's Survey Control Console (right-hand sidebar).

    Hosts every operator control for the live survey: ML model switch,
    detection threshold, hysteresis/trigger settings, background record/
    load/save, and survey start/stop/clear/download.
    """

    def __init__(self, service, plot_container: SpectrumPlotContainer):
        """Builds the sidebar's widgets.

        Args:
            service (RIIDCoreService): The shared backend service instance.
            plot_container (SpectrumPlotContainer): The sibling plot
                container, so viz-mode/log-scale changes made here can
                trigger an immediate redraw there.
        """
        self.service = service
        self.plot_container = plot_container
        self._assemble_ui()

    def _assemble_ui(self):
        """Builds and lays out every widget in the Survey Control Console."""
        with ui.column().classes('w-full gap-4'):
            ui.label('Survey Control Console').classes('text-xs font-bold uppercase tracking-widest border-b pb-1 w-full').style(f"color: {BRAND_COLORS['primary']}; border-color: #E2E8F0;")
            
            with ui.column().classes('w-full gap-2 bg-slate-50 p-3 rounded-md border shadow-inner').style('border-color: #E2E8F0;'):
                ui.label('ML Pipeline Settings').classes('text-[10px] font-bold text-zinc-500 uppercase tracking-wide')
                # Confidence-based slider (50%-99.9%) controlling
                # MlInference.CLASSIFICATION_THRESHOLD - the per-class
                # probability a detection must exceed to count as "detected".
                # Distinct from whether enough raw counts exist to attempt
                # inference at all, which MlInference gates internally
                # (see its own not-enough-counts check) - inference is always
                # attempted here regardless of this threshold.
                initial_threshold = getattr(self.service.ml_inference, 'CLASSIFICATION_THRESHOLD', 0.5)
                self.threshold_label = ui.label(f"Confidence Threshold ({initial_threshold * 100:.1f}%)").classes('text-xs text-zinc-700')
                self.threshold_slider = ui.slider(
                    min=0.50, max=0.999, step=0.001, value=initial_threshold,
                    on_change=self.trigger_threshold_change
                ).props('color=primary').classes('w-full')
                
                # A single "Automatic hysteresis" checkbox
                # now governs BOTH the ML trigger threshold (min_counts) and
                # the hysteresis reset threshold together, since they're
                # deeply related (both computed from the same
                # background-subtracted peak-channel rate trend). Checked
                # (default): both are live, read-only, auto-computed values -
                # the ML trigger adapts down for a faint source (see
                # RIIDCoreService.ML_TRIGGER_ABSOLUTE_FLOOR) so it doesn't take
                # minutes to first attempt a classification, while the reset
                # threshold adapts to give a consistent observation window
                # (see HYSTERESIS_TARGET_TIME_S). Unchecked: both become
                # directly operator-set controls with no adaptation at all -
                # what's shown always matches exactly what's applied, since
                # there's no separate "target vs effective" distinction once
                # adaptation is off.
                self.auto_hysteresis_checkbox = ui.checkbox(
                    'Automatic hysteresis', value=self.service.auto_hysteresis_enabled,
                    on_change=self.trigger_auto_hysteresis_toggle
                ).classes('text-xs text-zinc-700 font-medium')
                
                current_min_counts = self.service.ml_inference.get_min_counts()
                self.min_counts_auto_label = ui.label(f"ML pipeline trigger (auto): {current_min_counts} counts").classes('text-xs text-zinc-700')
                self.min_counts_label = ui.label(f"ML pipeline trigger: {current_min_counts} counts").classes('text-xs text-zinc-700')
                self.min_counts_slider = ui.slider(
                    min=1, max=200, step=1, value=current_min_counts,
                    on_change=self.trigger_min_counts_change
                ).props('color=primary').classes('w-full')
                
                self.max_cnt_label = ui.label(f"Spectrum auto-reset (auto): {self.service.max_counts_limit:,} counts").classes('text-xs text-zinc-700')
                self.max_cnt_manual_label = ui.label(f"Spectrum auto-reset: {self.service.max_counts_limit:,} counts").classes('text-xs text-zinc-700')
                self.max_cnt_input = ui.slider(
                    min=1, max=2000, step=1, value=self.service.max_counts_limit,
                    on_change=self.trigger_manual_hysteresis_change
                ).props('color=primary').classes('w-full')
                
                auto_enabled = self.service.auto_hysteresis_enabled
                self.min_counts_auto_label.set_visibility(auto_enabled)
                self.min_counts_label.set_visibility(not auto_enabled)
                self.min_counts_slider.set_visibility(not auto_enabled)
                self.max_cnt_label.set_visibility(auto_enabled)
                self.max_cnt_manual_label.set_visibility(not auto_enabled)
                self.max_cnt_input.set_visibility(not auto_enabled)

            # ============ LIVE SURVEY (primary workflow) ============
            # Directly below ML Pipeline Settings now that the diagnostic
            # console has moved to a collapsed panel at the bottom - these are
            # the two things an operator actually touches during a normal
            # survey, so they sit together at the top of the card.
            with ui.column().classes('w-full gap-2 bg-slate-50 p-3 rounded-md border shadow-inner').style('border-color: #E2E8F0;'):
                ui.label('Live Survey').classes('text-[10px] font-bold text-zinc-500 uppercase tracking-wide')
                
                # Shown instead of the controls below when no background exists
                # yet - a survey can't meaningfully start without one anyway
                # (see play_stop_btn's existing has_bg gate), so this makes
                # that requirement explicit rather than just leaving an empty
                # gap where the buttons would be.
                self.no_bg_message = ui.label("Load/record background to start").classes('text-xs text-zinc-500 italic text-center w-full py-2')
                self.no_bg_message.set_visibility(False)
                
                with ui.row().classes('w-full gap-2 no-wrap pt-1') as self.live_survey_controls_row:
                    self.play_stop_btn = ui.button('START', icon='play_arrow', on_click=self.trigger_play_stop_toggle)
                    self.play_stop_btn.style("background-color: #10B981 !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('flex-1 py-1.5 text-xs')
                    self.clear_btn = ui.button('RESTART', icon='restart_alt', on_click=self.trigger_clear)
                    self.clear_btn.style(f"background-color: {BRAND_COLORS['secondary']} !important; color: #FFFFFF !important; border: 1px solid #4A5568;").props('dense').classes('flex-1 py-1.5 text-xs')

                # Bundles the last spectrum shown here with the current
                # background into a downloadable .zip (both in .json and .spe).
                # Visible only once a background has settled (see refresh_widget_states).
                self.download_riid_btn = ui.button('Download Spectrum', icon='download', on_click=self.trigger_download_riid)
                self.download_riid_btn.style(f"background-color: {BRAND_COLORS['primary']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('w-full mt-1 py-1.5 text-xs')

            # ============ BACKGROUND SPECTRUM (collapsible) ============
            # Recording/loading/storing a background is a secondary, occasional
            # workflow compared to running a live survey - grouping it into a
            # single collapsed-by-default panel keeps it one click away without
            # competing for attention with the Live Survey card above.
            # Auto-expands while a capture is actively running (see
            # refresh_widget_states) so its progress bar stays visible.
            with ui.expansion('Background Spectrum', icon='ssid_chart', value=False) \
                    .classes('w-full bg-slate-50 border rounded-md').style('border-color: #E2E8F0;') \
                    .props('dense expand-separator header-class="text-xs font-bold text-zinc-700"') as self.bg_expansion:
                with ui.column().classes('w-full gap-2 p-2'):
                    self.bg_time_input = ui.number('BG Record Time (s)', value=self.service.bg_target_time, format='%d').classes('w-full text-xs').props('dense outlined')

                    self.bg_progress_bar = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-1.5 rounded transition-all').props('color=amber')
                    self.bg_progress_bar.set_visibility(False)

                    self.bg_btn = ui.button('RECORD BACKGROUND SPECTRUM', icon='security', on_click=self.trigger_bg)
                    self.bg_btn.style(f"background-color: {BRAND_COLORS['primary']} !important; color: #FFFFFF !important; font-weight: bold;").props('dense').classes('w-full py-2 text-xs shadow-md')

                    ui.separator().classes('bg-gray-200')

                    # Lets the operator load an already-saved background
                    # instead of recording a fresh one. Purely additive - the
                    # RECORD flow above is completely untouched.
                    with ui.column().classes('w-full gap-1') as self.load_bg_group:
                        with ui.row().classes('w-full gap-2 items-end'):
                            self.bg_file_select = ui.select(options=[], label='Load Pre-Recorded Background').props('dense outlined').classes('flex-1 text-xs')
                            ui.button(icon='refresh', on_click=self.refresh_bg_file_list).props('dense flat round').classes('text-zinc-600')
                        self.load_bg_btn = ui.button('LOAD SELECTED BACKGROUND', icon='folder_open', on_click=self.trigger_load_bg)
                        self.load_bg_btn.style(f"background-color: {BRAND_COLORS['secondary']} !important; border: 1px solid #4A5568; color: #FFFFFF !important;").props('dense').classes('w-full py-1.5 text-xs')
                    self.refresh_bg_file_list()

                    ui.separator().classes('bg-gray-200')

                    # Lets the operator persist the latest recorded
                    # background spectrum to disk (data/spectra/background/),
                    # independent of any survey/batch activity. Hidden while a NEW
                    # background capture is in progress to avoid ambiguity about
                    # which background would be saved.
                    self._build_save_bg_modal()
                    self.save_bg_btn = ui.button('Store Background Spectrum', icon='save', on_click=self.open_save_bg_dialog)
                    self.save_bg_btn.style(f"background-color: {BRAND_COLORS['secondary']} !important; border: 1px solid #4A5568; color: #FFFFFF !important;").props('dense').classes('w-full py-1.5 text-xs')

            # ============ SYSTEM CONSOLE (collapsible, closed by default) ============
            # Raw status readout - moved to the bottom and collapsed by default,
            # since it's diagnostic information the operator only needs to check
            # occasionally, not something that should compete for space with the
            # actual controls above. Light-themed now like the rest of the
            # sidebar, rather than the dark/terminal look it had before.
            with ui.expansion('System Console', icon='terminal', value=False) \
                    .classes('w-full bg-slate-50 border rounded-md').style('border-color: #E2E8F0;') \
                    .props('dense expand-separator header-class="text-xs font-bold text-zinc-700"'):
                with ui.column().classes('w-full gap-1 p-2 font-mono text-xs text-zinc-700'):
                    self.status_lbl = ui.label('SYSTEM: Syncing...')
                    self.bg_status_lbl = ui.label('BACKGROUND: Missing Profile')

    def trigger_threshold_change(self, e):
        """Updates the multi-label classification threshold live
        as the slider moves - unlike the model dropdown, this is not gated to
        idle-only, since adjusting sensitivity on the fly during an active
        survey is a reasonable, useful thing to do."""
        new_threshold = float(e.value)
        self.threshold_label.set_text(f"Confidence Threshold ({new_threshold * 100:.1f}%)")
        self.service.set_ml_classification_threshold(new_threshold)

    def trigger_min_counts_change(self, e):
        """Directly sets the ML pipeline's min_counts, live as the slider
        moves - only usable in manual mode (see trigger_auto_hysteresis_toggle),
        so this always takes effect immediately with no adaptation."""
        new_min_counts = int(e.value)
        self.min_counts_label.set_text(f"ML pipeline trigger: {new_min_counts} counts")
        self.service.set_ml_min_counts(new_min_counts)

    def trigger_auto_hysteresis_toggle(self, e):
        """Switches automatic mode for BOTH the ML
        trigger threshold and the hysteresis reset threshold together,
        swapping which controls are visible for each."""
        enabled = bool(e.value)
        self.service.set_auto_hysteresis_enabled(enabled)
        
        self.min_counts_auto_label.set_visibility(enabled)
        self.min_counts_label.set_visibility(not enabled)
        self.min_counts_slider.set_visibility(not enabled)
        self.max_cnt_label.set_visibility(enabled)
        self.max_cnt_manual_label.set_visibility(not enabled)
        self.max_cnt_input.set_visibility(not enabled)
        
        if not enabled:
            # Seed both manual controls with the last auto-computed value,
            # rather than whatever stale number was last shown before - a
            # reasonable starting point for the operator to adjust from.
            current_min_counts = self.service.ml_inference.get_min_counts()
            self.min_counts_slider.set_value(current_min_counts)
            self.min_counts_label.set_text(f"ML pipeline trigger: {current_min_counts} counts")
            self.max_cnt_input.set_value(self.service.max_counts_limit)
            self.max_cnt_manual_label.set_text(f"Spectrum auto-reset: {self.service.max_counts_limit:,} counts")

    def trigger_manual_hysteresis_change(self, e):
        """Sets the operator's manual peak-single-channel-count
        threshold - only takes effect while auto-reset is disabled."""
        new_threshold = int(e.value or self.service.DEFAULT_MAX_COUNTS_LIMIT)
        self.max_cnt_manual_label.set_text(f"Spectrum auto-reset: {new_threshold:,} counts")
        self.service.set_manual_hysteresis_threshold(new_threshold)

    def trigger_bg(self):
        """Starts a fresh background recording for the configured duration."""
        logger.warning(f"[USER_ACTION] Operator clicked RECORD BACKGROUND SPECTRUM button. Duration: {self.bg_time_input.value}s")
        self.service.start_background_recording(int(self.bg_time_input.value or self.service.DEFAULT_BG_TARGET_TIME_S))

    def refresh_bg_file_list(self):
        """Repopulates the load-background dropdown from whatever's currently
        in data/spectra/background/ (via the service, which owns that path)."""
        files = self.service.list_available_background_files()
        self.bg_file_select.options = files
        self.bg_file_select.update()

    def trigger_load_bg(self):
        """Loads the background spectrum selected in the dropdown."""
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
        """Prompt dialog that asks for a file name
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
                """Validates the format checkboxes and saves the background spectrum."""
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
        """Opens the save-background dialog with a freshly-suggested filename."""
        # Re-suggest a fresh timestamp prefix every time the dialog is opened,
        # rather than leaving a stale one from a previous save attempt.
        self.bg_filename_input.set_value(f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_background")
        self.save_bg_dialog.open()

    def trigger_play_stop_toggle(self):
        """Single control that starts a survey when idle, or halts it when running.
        STOP doesn't wipe the spectrum - a separate RESTART/CLEAR button (see
        trigger_clear) is used for that instead."""
        if self.service.state == 'IDLE':
            self.trigger_start()
        else:
            self.trigger_stop()

    def trigger_start(self):
        """Starts (or resumes) the continuous survey."""
        logger.warning("[USER_ACTION] Operator clicked START continuous survey.")
        self.service.start_continuous_survey()

    def trigger_stop(self):
        """Stops the currently running survey/recording."""
        logger.warning("[USER_ACTION] Operator clicked STOP survey button.")
        self.service.stop_execution()

    def trigger_clear(self):
        """Wipes the accumulated survey spectrum, preserving the background."""
        logger.warning("[USER_ACTION] Operator clicked RESTART button - wiping accumulated survey spectrum (background preserved).")
        self.service.clear_survey_data()

    def trigger_download_riid(self):
        """Bundles the current RIID spectrum + background into a downloadable zip."""
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

        # Multi-client sync: this app can have several clients connected at
        # once (e.g. a phone and a desktop both viewing the same
        # instrument) - they all share the SAME backend_service singleton,
        # so a change made on one device already takes effect correctly in
        # the backend immediately. What was missing is the other direction:
        # each device's own slider/checkbox widgets were only ever PUSHED to
        # the backend via their own on_change handlers, never PULLED back
        # into sync with a change made from a different device - so a
        # threshold changed on device A took effect, but device B's slider
        # kept showing its own stale position indefinitely. Comparing before
        # calling set_value() avoids fighting an in-progress drag on this
        # same device (on_change only fires once a drag releases, so the
        # backend value can't change mid-drag anyway) and avoids
        # unnecessary re-renders when nothing has actually changed.
        current_threshold = self.service.ml_inference.CLASSIFICATION_THRESHOLD
        if abs(self.threshold_slider.value - current_threshold) > 1e-6:
            self.threshold_slider.set_value(current_threshold)
            self.threshold_label.set_text(f"Confidence Threshold ({current_threshold * 100:.1f}%)")
        
        current_auto_enabled = self.service.auto_hysteresis_enabled
        if self.auto_hysteresis_checkbox.value != current_auto_enabled:
            self.auto_hysteresis_checkbox.set_value(current_auto_enabled)
            self.min_counts_auto_label.set_visibility(current_auto_enabled)
            self.min_counts_label.set_visibility(not current_auto_enabled)
            self.min_counts_slider.set_visibility(not current_auto_enabled)
            self.max_cnt_label.set_visibility(current_auto_enabled)
            self.max_cnt_manual_label.set_visibility(not current_auto_enabled)
            self.max_cnt_input.set_visibility(not current_auto_enabled)
        
        # get_min_counts() is always the current, accurate value regardless
        # of mode - auto-computed each tick in auto mode, directly
        # operator-set in manual mode (see set_ml_min_counts). Update
        # whichever display is relevant for the current mode.
        current_min_counts = self.service.ml_inference.get_min_counts()
        if current_auto_enabled:
            self.min_counts_auto_label.set_text(f"ML pipeline trigger (auto): {current_min_counts} counts")
        elif self.min_counts_slider.value != current_min_counts:
            self.min_counts_slider.set_value(current_min_counts)
            self.min_counts_label.set_text(f"ML pipeline trigger: {current_min_counts} counts")
        
        if not current_auto_enabled and self.max_cnt_input.value != self.service.max_counts_limit:
            self.max_cnt_input.set_value(self.service.max_counts_limit)
            self.max_cnt_manual_label.set_text(f"Spectrum auto-reset: {self.service.max_counts_limit:,} counts")

        # Reflects the backend's current dynamically-computed
        # hysteresis threshold - only actually changes while a survey is
        # running (that's the only time _compute_dynamic_hysteresis_threshold
        # gets called), but kept live-updating here regardless so it never
        # shows a stale value from a previous session. Only updates the label
        # (auto mode's read-only display) - the manual input, when visible,
        # holds the operator's own value and isn't touched here.
        if self.service.auto_hysteresis_enabled:
            self.max_cnt_label.set_text(f"Spectrum auto-reset (auto): {self.service.max_counts_limit:,} counts")

        # Calculate exact Counts Per Second (CPS) metrics based directly on MCA hardware live-time
        if is_survey_running and self.service.live_spectrum:
            total_counts = sum(self.service.live_spectrum)
            # Fetch active survey live-time duration in milliseconds directly from the MCA hardware
            survey_ms = float(getattr(self.service, 'survey_hardware_live_time_ms', 0.0) or 0.0)
            survey_seconds = float(survey_ms / 1000.0)
            
            # Safe boundary division check calculates precise CPS rate values
            cps_rate = float(total_counts / survey_seconds) if survey_seconds > 0.0 else 0.0
            
            # Formally display the calculated hardware CPS metric on the panel view label
            self.status_lbl.set_text(
                f"OP_STATE: SURVEY ACTIVE | TIME: {survey_seconds:.1f}s | "
                f"COUNTS: {total_counts} | RATE: {cps_rate:.2f} cps"
            )
        else:
            self.status_lbl.set_text(f"OP_STATE: {self.service.status_text.upper()}")

        if has_bg:
            self.bg_status_lbl.set_text("BACKGROUND SPECTRUM: CALIBRATED (READY)")
            self.bg_status_lbl.style("color: #047857;")
        else:
            self.bg_status_lbl.set_text("BACKGROUND SPECTRUM: ABSENT (LOCKED)")
            self.bg_status_lbl.style("color: #B91C1C;")

        # Nudges a first-time (or otherwise background-less) operator toward
        # recording one: a gentle pulsing orange border on the panel itself,
        # using Tailwind's built-in animate-pulse - no custom CSS/JS, and
        # since the panel is collapsed by default, only its header row is
        # visible while pulsing, so this stays subtle rather than flickering
        # a large area. Off during an active BG capture (the panel already
        # auto-expands then, so the cue would be redundant) and off as soon
        # as a background exists.
        needs_bg_highlight = not has_bg and not is_bg_running
        if needs_bg_highlight:
            self.bg_expansion.classes(add='border-2 animate-pulse').style(f"border-color: {BRAND_COLORS['subtracted_trace']};")
        else:
            self.bg_expansion.classes(remove='border-2 animate-pulse').style('border-color: #E2E8F0;')

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

        # Loading a pre-recorded background is only meaningful while
        # idle (matches the backend's own state guard in load_background_spectrum).
        self.load_bg_group.set_visibility(is_idle)

        # Only offer saving when there's actually a background to
        # save, and only while fully idle - not during a new BG capture (which
        # background would get written is ambiguous), and not during an active
        # survey (keeps this control's visibility consistent with the
        # load-background picker just above, and avoids saving mid-run).
        self.save_bg_btn.set_visibility(has_bg and is_idle)

        # Visible once the background has "settled" - it exists and
        # isn't currently being (re)captured. Unlike save_bg_btn above, this
        # stays visible during an active survey too, since downloading the
        # in-progress/last-shown RIID spectrum together with the background is
        # exactly the point of this button.
        self.download_riid_btn.set_visibility(has_bg and not is_bg_running)

        # Single toggle button: shows START when idle (ready to run), STOP while a
        # survey/background/batch run is in progress. Doesn't erase the spectrum
        # itself - clearing is a separate, always-visible RESTART button (see
        # self.clear_btn / trigger_clear).
        if is_idle:
            self.play_stop_btn.set_text('START')
            self.play_stop_btn.props('icon=play_arrow')
            self.play_stop_btn.style("background-color: #10B981 !important; color: #FFFFFF !important; font-weight: bold;")
        else:
            self.play_stop_btn.set_text('STOP')
            self.play_stop_btn.props('icon=stop')
            self.play_stop_btn.style(f"background-color: {BRAND_COLORS['crimson_trace']} !important; color: #FFFFFF !important; font-weight: bold;")

        self.play_stop_btn.set_visibility((is_idle and hw_ok and has_bg) or not is_idle)

        # CLEAR only touches the accumulated survey spectrum. It stays available
        # both when idle and during an active survey so it doesn't require STOP
        # first; it's hidden only during BG recording / batch runs where clearing
        # would be ambiguous or unsafe.
        self.clear_btn.set_visibility(is_idle or is_survey_running)

        # Replaces the controls entirely with an explicit message when idle
        # with no background recorded yet - a survey can't meaningfully start
        # in that state anyway (play_stop_btn's own gate above already
        # prevents it), so this makes the reason obvious instead of just
        # leaving START invisible with no explanation. download_riid_btn is
        # already hidden in this case by its own has_bg gate a few lines up.
        show_no_bg_message = is_idle and not has_bg
        self.no_bg_message.set_visibility(show_no_bg_message)
        self.live_survey_controls_row.set_visibility(not show_no_bg_message)