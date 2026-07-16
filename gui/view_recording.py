import os
import json
import asyncio
from datetime import datetime
from nicegui import ui
from state_engine import SpectrumAcquisitionSystem
from config import BRAND_COLORS, logger

class SpectrumRecordingPanel:
    # Fixed on purpose: kept constant across data updates so Plotly preserves the
    # user's manual zoom/pan instead of resetting it every time the batch spectrum
    # refreshes. Autozoom then only happens via the user's own action (double-click
    # or the toolbar's Autoscale/Reset-axes button).
    PLOT_UIREVISION = 'batch_recording_plot'

    def __init__(self, service):
        self.service = service
        self.system = service.system
        # Tracks the last batch spectrum fingerprint actually rendered, so the
        # heavy record_plot_container.clear()+ui.plotly() redraw can be skipped
        # while no batch recording is active and nothing changed (issue #43).
        self._last_batch_render_signature = None
        # The live ui.plotly widget, kept alive and updated in place across data
        # refreshes (rather than torn down and recreated) so the browser-side plot
        # instance - and the user's zoom/pan state - persists.
        self._plot_widget = None
        self.render_layout()

    def render_layout(self):
        """Assembles a dual-column wide layout splitting forms from tracking charts."""
        with ui.row().classes('w-full gap-3 items-stretch no-wrap'):
            
            # LEFT CARD: Source Table Library Configurations Mapping
            with ui.card().classes('p-4 rounded-lg border shadow-md bg-white gap-3').style('width: 50%; border-color: #E2E8F0;'):
                ui.markdown("📝 **Centralized Sources Matrix:** Link physical isotope sources utilizing persistent library records.").classes('text-xs text-zinc-600')
                ui.label('Active Radiation Sources Directory').classes('text-xs font-bold mt-1').style(f"color: {BRAND_COLORS['primary']};")
                
                source_columns = [
                    {'name': 'SourceID', 'label': 'Source ID (Code)', 'field': 'Source ID', 'align': 'left'},
                    {'name': 'Isotope', 'label': 'Isotope', 'field': 'Isotope', 'align': 'left'},
                    {'name': 'Activity', 'label': 'Activity (kBq)', 'field': 'Activity', 'align': 'center'},
                    {'name': 'Date', 'label': 'Ref Date', 'field': 'Date', 'align': 'center'},
                    {'name': 'Type', 'label': 'Type', 'field': 'Type', 'align': 'center'},
                    {'name': 'Form', 'label': 'Form', 'field': 'Form', 'align': 'center'},
                    {'name': 'Distance', 'label': 'Distance (cm)', 'field': 'Distance', 'align': 'center'},
                    {'name': 'actions', 'label': 'Action Controls', 'field': 'actions', 'align': 'center'}
                ]
                
                self.sources_table = ui.table(columns=source_columns, rows=self.system.runtime_metadata['Sources'], row_key='Source ID')
                self.sources_table.props('dense flat bordered wrap-cells').classes('w-full text-xs').style('max-height: 160px;')
                self.sources_table.add_slot('body-cell-actions', r'''
                    <q-td :props="props">
                        <q-btn flat round dense icon="delete" size="sm" color="negative" @click="$parent.$emit('delete_source', props.row)" />
                    </q-td>
                ''')

                def delete_source_handler(msg):
                    row_to_del = msg.args
                    logger.warning(f"[USER_ACTION] Operator deleted radioactive isotope source reference row match: {row_to_del['Source ID']}")
                    self.system.runtime_metadata['Sources'] = [s for s in self.system.runtime_metadata['Sources'] if s['Source ID'] != row_to_del['Source ID']]
                    self.sources_table.rows = self.system.runtime_metadata['Sources']
                    ui.notify(f"Source registry link purged.", color=BRAND_COLORS['crimson_trace'])
                
                self.sources_table.on('delete_source', delete_source_handler)
                self._build_append_modal()
            # RIGHT CARD: Persistent Plotly Canvas and Polling Controllers Readout
            with ui.card().classes('p-4 rounded-lg border shadow-md bg-white gap-3 flex-1').style('width: 50%; border-color: #E2E8F0;'):
                ui.label('Batch Recording Output & Controls').classes('text-xs font-bold uppercase tracking-wider text-zinc-700')
                self.record_plot_container = ui.column().classes('w-full items-center justify-center rounded-lg border p-1 bg-white')
                
                with ui.row().classes('w-full gap-2 items-center justify-between mt-1 pt-1 border-t'):
                    self.time_input = ui.number('Live-Time (s)', value=self.service.batch_target_time, format='%d').props('dense outlined').classes('w-24 text-xs')
                    self.runs_input = ui.number('Recordings (Runs)', value=self.service.batch_total_runs, format='%d').props('dense outlined min=1').classes('w-28 text-xs')
                    self.prefix_input = ui.input('Filename Prefix', value=self.service.batch_prefix).props('dense outlined').classes('flex-1 text-xs')
                    
                    with ui.row().classes('gap-1'):
                        self.start_btn = ui.button('Start', icon='play_arrow', on_click=self.trigger_batch_start)
                        self.start_btn.style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").props('dense').classes('text-xs')
                        self.stop_btn = ui.button('Stop', icon='stop', on_click=self.trigger_batch_stop)
                        self.stop_btn.style(f"background-color: {BRAND_COLORS['crimson_trace']}; color: #FFFFFF; font-weight: bold;").props('dense').classes('text-xs')

                self.progress_bar = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-1.5 mt-1 rounded').props('color=primary')
                self.status_label = ui.label('Status: Ready').classes('text-xs font-mono text-zinc-500 q-my-none')
                
                ui.timer(1.0, self.sync_ui_state)

    def trigger_batch_start(self):
        logger.warning(f"[USER_ACTION] Operator triggered automated spectrum multi-run batch recording. prefix='{self.prefix_input.value}' | runs={self.runs_input.value}")
        self.service.start_batch_recording(
            target_time=int(self.time_input.value or 30),
            total_runs=int(self.runs_input.value or 1),
            prefix=str(self.prefix_input.value or "spectrum")
        )

    def trigger_batch_stop(self):
        logger.warning("[USER_ACTION] Operator requested STOP multi-run batch recording.")
        self.service.stop_execution()

    def sync_ui_state(self):
        """Pulls ongoing multi-run telemetry fields from server memory instantly upon page visibility re-attachment."""
        is_batch = self.service.state == 'BATCH_RECORDING'
        self.start_btn.set_visibility(not is_batch and self.service.state == 'IDLE' and self.service.is_hardware_available)
        self.stop_btn.set_visibility(is_batch)
        
        self.status_label.set_text(f"Status: {self.service.batch_status_text}")
        if is_batch and self.service.batch_target_time > 0:
            self.progress_bar.set_value(min(self.service.batch_elapsed_seconds / self.service.batch_target_time, 1.0))
        else:
            self.progress_bar.set_value(0.0)
        
        spectrum = self.service.batch_spectrum
        render_signature = (len(spectrum) if spectrum else 0, sum(spectrum) if spectrum else 0)
        
        # While no batch run is active, only redraw the canvas if the spectrum
        # actually differs from what's already shown - otherwise this rebuilds an
        # identical Plotly figure every second, causing a visible "blink".
        if not is_batch and render_signature == self._last_batch_render_signature:
            return
        self._last_batch_render_signature = render_signature
        
        self.refresh_recording_canvas(spectrum)

    def refresh_recording_canvas(self, spectrum_data: list):
        if not spectrum_data:
            self.record_plot_container.clear()
            self._plot_widget = None
            with self.record_plot_container, ui.column().classes('w-full h-[240px] items-center justify-center text-zinc-400 gap-1'):
                ui.icon('radioactivity', size='md').style(f"color: {BRAND_COLORS['accent']};")
                ui.label("Batch Analyzer Idle - Configure Fields and Press Start").classes('text-[11px] font-bold text-zinc-600')
            return

        num_channels = len(spectrum_data)
        prof = self.system.hw_profile
        a0 = float(prof.get('calib_a0', 0.0))
        a1 = float(prof.get('calib_a1', 1.0))
        a2 = float(prof.get('calib_a2', 0.0))
        energy_axis = [a0 + (a1 * ch) + (a2 * (ch ** 2)) for ch in range(num_channels)]
        
        fig = {
            'data': [{'x': energy_axis, 'y': spectrum_data, 'type': 'scatter', 'mode': 'lines', 'line': {'color': BRAND_COLORS['primary'], 'width': 1.2}}],
            'layout': {
                'xaxis': {'title': 'Energy (keV)', 'tickfont': {'size': 8}, 'gridcolor': '#F3F4F6', 'autorange': True},
                'yaxis': {'title': 'Counts', 'type': 'log', 'tickfont': {'size': 8}, 'gridcolor': '#F3F4F6'},
                'margin': {'l': 40, 'r': 15, 't': 10, 'b': 30}, 'plot_bgcolor': '#FFFFFF', 'paper_bgcolor': '#FFFFFF', 'showlegend': False,
                'uirevision': self.PLOT_UIREVISION,
            }
        }
        if self._plot_widget is None:
            self.record_plot_container.clear()
            with self.record_plot_container:
                self._plot_widget = ui.plotly(fig).classes('w-full h-[240px]')
        else:
            # Push new data into the existing widget instead of recreating it, so
            # the user's manual zoom/pan on this plot survives the data refresh.
            self._plot_widget.figure = fig
            self._plot_widget.update()
    def _build_append_modal(self):
        with ui.dialog() as source_dialog, ui.card().classes('p-4 w-96 space-y-3'):
            ui.label('Link Database Source Profile').classes('text-sm font-bold text-blue-600')
            avail_ids = list(self.system.sources_db.keys())
            code_select = ui.select(options=avail_ids, label='Select Existing Source Code').props('dense outlined').classes('w-full')
            
            ui.markdown("--- *Or Register New Source into Database File* ---").classes('text-[10px] text-center text-zinc-400 block w-full q-my-none')
            new_code_input = ui.input('New Source ID Code').props('dense outlined').classes('w-full text-xs')
            new_iso = ui.input('Isotope Symbol', value='Cs-137').props('dense outlined').classes('w-full text-xs')
            new_act = ui.number('Reference Activity (kBq)', value=100.0, format='%.2f').props('dense outlined').classes('w-full text-xs')
            new_date = ui.input('Reference Date (YYYY/MM/DD)', value=datetime.now().strftime('%Y/%m/%d')).props('dense outlined').classes('w-full text-xs')
            new_type = ui.input('Material Type', value='Source').props('dense outlined').classes('w-full text-xs')
            new_form = ui.input('Material Form Shape', value='point').props('dense outlined').classes('w-full text-xs')
            
            ui.markdown("--- *Volatile Geometrical Runtime Parameters* ---").classes('text-[10px] text-center text-zinc-400 block w-full q-my-none')
            dist_input = ui.input('Distance to Detector (cm)', value='20').props('dense outlined').classes('w-full text-xs')
            
            def commit_source_selection():
                target_code = code_select.value
                if new_code_input.value:
                    target_code = str(new_code_input.value).strip()
                    logger.warning(f"[USER_ACTION] Operator added a new isotope source configuration record into inventory library file: {target_code}")
                    self.system.sources_db[target_code] = {
                        "isotope": new_iso.value, "activity": float(new_act.value or 0.0),
                        "date": new_date.value, "type": new_type.value, "form": new_form.value
                    }
                    self.system.save_sources_db()
                    ui.notify(f"Source {target_code} saved to sources.json database.", type="positive")

                if not target_code or target_code not in self.system.sources_db:
                    ui.notify("Please select a Source ID or register a new one.", type="negative")
                    return

                metrics = self.system.sources_db[target_code]
                logger.info(f"[USER_ACTION] Appended radiation source reference '{target_code}' into the transient run parameters.")
                self.system.runtime_metadata['Sources'].append({
                    "Source ID": target_code, 
                    "Isotope": metrics["isotope"],
                    "Activity": f"{metrics['activity']:.2f} kBq", 
                    "Date": metrics["date"],
                    "Type": metrics["type"], 
                    "Form": metrics["form"], 
                    "Distance": f"{dist_input.value or '20'} cm"
                })
                self.sources_table.rows = self.system.runtime_metadata['Sources']
                source_dialog.close()

            with ui.row().classes('w-full justify-between pt-1'):
                ui.button('Append into Run', icon='add_circle', on_click=commit_source_selection).props('dense color=primary')
                ui.button('Cancel', on_click=source_dialog.close).props('dense outline')

        ui.button('Add Radioactive Source Entry', icon='add', on_click=source_dialog.open).props('outline dense').classes('text-xs').style(f"color: {BRAND_COLORS['primary']};")