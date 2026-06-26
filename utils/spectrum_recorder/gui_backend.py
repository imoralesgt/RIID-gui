import os
import json
import asyncio
from datetime import datetime
from nicegui import ui
from state_engine import SpectrumAcquisitionSystem
from config import BRAND_COLORS, logger
from core.daq_commands import DaqCommands

is_recording_active = False

def force_abort_recording():
    global is_recording_active
    is_recording_active = False
    logger.info("Hardware run execution sequence stop signal toggled by operator instruction.")


def render_volatile_environment_tab(system: SpectrumAcquisitionSystem):
    """Assembles highly compressed form inputs and compact table data grids."""
    ui.markdown("📝 **Volatile Run Configs:** Managed exclusively in the GUI for the current run only.").classes('text-xs q-my-none text-zinc-600')
    
    with ui.row().classes('w-full gap-2 mt-1'):
        ui.input('Material Type', value=system.runtime_metadata['Material type'],
                 on_change=lambda e: system.runtime_metadata.update({'Material type': e.value})).props('dense outlined').classes('flex-1')
        ui.input('Material Form', value=system.runtime_metadata['Material form'],
                 on_change=lambda e: system.runtime_metadata.update({'Material form': e.value})).props('dense outlined').classes('flex-1')

    with ui.row().classes('w-full justify-between items-center mt-2 mb-1'):
        ui.label('Active Isotopic Standard Reference Radioactive Sources').classes('text-xs font-bold').style(f"color: {BRAND_COLORS['primary']};")
    
    source_columns = [
        {'name': 'Isotope', 'label': 'Isotope', 'field': 'Isotope', 'align': 'left'},
        {'name': 'Distance', 'label': 'Distance (cm)', 'field': 'Source to detector distance (cm)', 'align': 'center'},
        {'name': 'SourceID', 'label': 'Source ID', 'field': 'Source ID', 'align': 'center'},
        {'name': 'Activity', 'label': 'Ref Activity', 'field': 'Reference Activity', 'align': 'center'},
        {'name': 'Date', 'label': 'Ref Date', 'field': 'Reference Date', 'align': 'center'},
        {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'align': 'center'}
    ]
    
    sources_table = ui.table(columns=source_columns, rows=system.runtime_metadata['Sources'], row_key='Source ID')
    sources_table.props('dense flat bordered wrap-cells virtual-scroll').classes('w-full text-xs')
    sources_table.style('max-height: 110px;')
    sources_table.add_slot('body-cell-actions', r'''
        <q-td :props="props">
            <q-btn flat round dense icon="delete" size="sm" color="negative" @click="$parent.$emit('delete_source', props.row)" />
        </q-td>
    ''')

    def delete_source_handler(msg):
        row_to_del = msg.args
        system.runtime_metadata['Sources'] = [s for s in system.runtime_metadata['Sources'] if s['Source ID'] != row_to_del['Source ID']]
        sources_table.rows = system.runtime_metadata['Sources']
        ui.notify(f"Source row entry {row_to_del['Source ID']} removed.", color=BRAND_COLORS['crimson_trace'])
    sources_table.on('delete_source', delete_source_handler)

    with ui.dialog() as source_dialog, ui.card().classes('p-3 w-80 space-y-2'):
        ui.label('Add New Radiation Source Row').classes('text-sm font-bold text-blue-600')
        new_iso = ui.input('Isotope', value='Cs137').props('dense outlined')
        new_dist = ui.input('Distance (cm)', value='20').props('dense outlined')
        new_id = ui.input('Source ID', value=f"G{len(system.runtime_metadata['Sources']) + 82:03d}").props('dense outlined')
        
        with ui.row().classes('w-full items-center gap-2'):
            new_act = ui.number('Activity Value', value=666.5, format='%.2f').props('dense outlined').classes('flex-1')
            unit_radio = ui.radio(['kBq', 'uCi'], value='kBq').props('inline dense')
        new_date = ui.input('Reference Date (YYYY/MM/DD)', value='2015/07/06').props('dense outlined')
        
        def save_source_modal_form():
            raw_val = float(new_act.value or 0.0)
            converted_kbq = raw_val * 37.0 if unit_radio.value == 'uCi' else raw_val
            stored_activity_str = f"{converted_kbq:.2f}kBq"
            
            system.runtime_metadata['Sources'].append({
                "Isotope": new_iso.value, "Source to detector distance (cm)": new_dist.value,
                "Source ID": new_id.value, "Reference Activity": stored_activity_str, "Reference Date": new_date.value
            })
            sources_table.rows = system.runtime_metadata['Sources']
            source_dialog.close()
        ui.button('Add Row', icon='check', on_click=save_source_modal_form).props('dense color=primary')

    ui.button('Append New Radiation Source Element', icon='add', on_click=source_dialog.open).props('outline dense').classes('text-xs mt-1').style(f"color: {BRAND_COLORS['primary']}; border-color: {BRAND_COLORS['primary']};")
    with ui.row().classes('w-full justify-between items-center mt-2 mb-1'):
        ui.label('Experimental Shielding Materials / Absorbers Layer').classes('text-xs font-bold').style(f"color: {BRAND_COLORS['primary']};")
    
    shield_columns = [
        {'name': 'Material', 'label': 'Material Element Symbol', 'field': 'Material', 'align': 'left'},
        {'name': 'Thickness', 'label': 'Thickness (mm)', 'field': 'Thickness (mm)', 'align': 'center'},
        {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'align': 'center'}
    ]
    
    attenuators_table = ui.table(columns=shield_columns, rows=system.runtime_metadata['Attenuators'], row_key='Material')
    attenuators_table.props('dense flat bordered wrap-cells virtual-scroll').classes('w-full text-xs')
    attenuators_table.style('max-height: 90px;')
    
    attenuators_table.add_slot('body-cell-actions', r'''
        <q-td :props="props">
            <q-btn flat round dense icon="delete" size="sm" color="negative" @click="$parent.$emit('delete_shield', props.row)" />
        </q-td>
    ''')

    def delete_shield_handler(msg):
        row_to_del = msg.args
        system.runtime_metadata['Attenuators'] = [a for a in system.runtime_metadata['Attenuators'] if a['Material'] != row_to_del['Material']]
        attenuators_table.rows = system.runtime_metadata['Attenuators']
        ui.notify(f"Shield row material {row_to_del['Material']} removed.", color=BRAND_COLORS['crimson_trace'])
    attenuators_table.on('delete_shield', delete_shield_handler)

    with ui.dialog() as shield_dialog, ui.card().classes('p-3 w-80 space-y-2'):
        ui.label('Add New Shielding Layer Absorber Row').classes('text-sm font-bold text-blue-600')
        new_mat = ui.input('Material Symbol', value='Pb').props('dense outlined')
        new_thick = ui.input('Thickness (mm)', value='1').props('dense outlined')
        
        def save_shield_modal_form():
            system.runtime_metadata['Attenuators'].append({"Material": new_mat.value, "Thickness (mm)": new_thick.value})
            attenuators_table.rows = system.runtime_metadata['Attenuators']
            shield_dialog.close()
        ui.button('Add Row', icon='check', on_click=save_shield_modal_form).props('dense color=primary')

    ui.button('Append Shielding Attenuator Block', icon='add', on_click=shield_dialog.open).props('outline dense').classes('text-xs mt-1').style(f"color: {BRAND_COLORS['primary']}; border-color: {BRAND_COLORS['primary']};")


def render_calibration_persistent_panel(system: SpectrumAcquisitionSystem, tab_calibration):
    """Assembles a space-saving micro calibration forms grid panel with integrated Advanced hardware parameters section."""
    with ui.tab_panel(tab_calibration).classes('space-y-1.5 p-0'):
        with ui.row().classes('w-full gap-2 mt-1'):
            ui.input('Analyzer Name', value=system.hw_profile['Analyzer name'], on_change=lambda e: system.hw_profile.update({'Analyzer name': e.value})).props('dense outlined').classes('flex-1')
            ui.input('Detector Type', value=system.hw_profile['Detector type'], on_change=lambda e: system.hw_profile.update({'Detector type': e.value})).props('dense outlined').classes('flex-1')
        
        ui.input('Detector Size', value=system.hw_profile['Detector size'], on_change=lambda e: system.hw_profile.update({'Detector size': e.value})).props('dense outlined').classes('w-full')
        
        with ui.row().classes('w-full gap-2'):
            ui.input('Detector Model Number', value=system.hw_profile['Detector type number'], on_change=lambda e: system.hw_profile.update({'Detector type number': e.value})).props('dense outlined').classes('flex-1')
            ui.input('Detector Serial Number', value=system.hw_profile['Detector serial number'], on_change=lambda e: system.hw_profile.update({'Detector serial number': e.value})).props('dense outlined').classes('flex-1')
        
        ui.label('Energy Calibration Coefficients ($MCA_CAL)').classes('text-xs font-bold mt-0.5').style(f"color: {BRAND_COLORS['primary']};")
        with ui.row().classes('w-full gap-2'):
            ui.number('Offset / a0', value=system.hw_profile['calib_a0'], format='%.5f', on_change=lambda e: system.hw_profile.update({'calib_a0': e.value})).props('dense outlined').classes('flex-1')
            ui.number('Linear / a1', value=system.hw_profile['calib_a1'], format='%.5f', on_change=lambda e: system.hw_profile.update({'calib_a1': e.value})).props('dense outlined').classes('flex-1')
            ui.number('Quadratic / a2', value=system.hw_profile['calib_a2'], format='%.3e', on_change=lambda e: system.hw_profile.update({'calib_a2': e.value})).props('dense outlined').classes('flex-1')

        with ui.expansion('Advanced Settings', icon='settings').classes('w-full border rounded text-xs q-pa-none').props('dense'):
            with ui.column().classes('w-full p-2 gap-2 bg-zinc-50'):
                with ui.row().classes('w-full gap-2'):
                    ui.number('Analog Gain (vga_gain_coarse)', value=system.hw_profile['vga_gain_coarse'], format='%.1f',
                              on_change=lambda e: system.hw_profile.update({'vga_gain_coarse': e.value})).props('dense outlined').classes('flex-1')
                    ui.number('Smoothing Factor', value=system.hw_profile['smoothing_factor'], format='%d',
                              on_change=lambda e: system.hw_profile.update({'smoothing_factor': int(e.value or 2)})).props('dense outlined').classes('flex-1')
                with ui.row().classes('w-full gap-2'):
                    ui.number('Shaper Peaking Time (s)', value=system.hw_profile['shaper_s_tau_pk'], format='%.3e',
                              on_change=lambda e: system.hw_profile.update({'shaper_s_tau_pk': e.value})).props('dense outlined').classes('flex-1')
                    ui.number('Shaper Flat Top (s)', value=system.hw_profile['shaper_s_tau_pk_top'], format='%.3e',
                              on_change=lambda e: system.hw_profile.update({'shaper_s_tau_pk_top': e.value})).props('dense outlined').classes('flex-1')
                ui.number('Baseline Restorer Gain (blr_s_threshold_gain)', value=system.hw_profile['blr_s_threshold_gain'], format='%.1f',
                          on_change=lambda e: system.hw_profile.update({'blr_s_threshold_gain': e.value})).props('dense outlined').classes('w-full')

        with ui.row().classes('w-full mt-1 justify-end'):
            def save_profile_to_json_file():
                system.db[system.serial_number] = {k: v for k, v in system.hw_profile.items()}
                if system.save_hardware_db():
                    ui.notify("Hardware properties updated!", type="positive")
            ui.button('Commit Calibration Parameters', icon='save', on_click=save_profile_to_json_file).style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF; font-weight: bold;").classes('py-0.5 px-2 text-xs')
def update_interactive_plotly_canvas(system: SpectrumAcquisitionSystem, plot_container, spectrum_data: list):
    """Repaints the active Plotly frame converting channels to keV using hardware coefficients."""
    plot_container.clear()
    
    if not spectrum_data:
        with plot_container, ui.column().classes('w-full h-[360px] items-center justify-center p-4 text-center text-zinc-400 gap-1'):
            ui.icon('analytics', size='lg').style(f"color: {BRAND_COLORS['accent']};")
            ui.label(f"Analyzer Channel Standby [S/N: {system.serial_number}]").classes('text-xs font-bold text-zinc-700')
            ui.label("Configure parameters and click 'Start' to begin keV acquisition sequence.").classes('text-[10px] text-zinc-500')
        return

    num_channels = len(spectrum_data)
    a0 = float(system.hw_profile.get("calib_a0", 0.0))
    a1 = float(system.hw_profile.get("calib_a1", 1.0))
    a2 = float(system.hw_profile.get("calib_a2", 0.0))
    
    calibrated_energy_axis_kev = [a0 + (a1 * ch) + (a2 * (ch ** 2)) for ch in range(num_channels)]
    
    plotly_fig = {
        'data': [{'x': calibrated_energy_axis_kev, 'y': spectrum_data, 'type': 'scatter', 'mode': 'lines', 'line': {'color': BRAND_COLORS['crimson_trace'], 'width': 1.0}}],
        'layout': {
            'title': {'text': f"Calibrated Energy Spectrum [S/N: {system.serial_number}]", 'font': {'size': 10, 'color': BRAND_COLORS['secondary']}},
            'xaxis': {'title': 'Energy (keV)', 'titlefont': {'size': 8}, 'tickfont': {'size': 7}, 'gridcolor': '#F3F4F6', 'autorange': True},
            'yaxis': {'title': 'Counts (N)', 'type': 'log', 'titlefont': {'size': 8}, 'tickfont': {'size': 7}, 'gridcolor': '#F3F4F6'},
            'margin': {'l': 35, 'r': 10, 't': 22, 'b': 22}, 'hovermode': 'x unified', 'plot_bgcolor': '#FFFFFF', 'paper_bgcolor': '#FFFFFF', 'showlegend': False
        }
    }
    with plot_container:
        ui.plotly(plotly_fig).classes('w-full h-[360px]')
def render_acquisition_telemetry_commands(system: SpectrumAcquisitionSystem, plot_container):
    """Assembles command hubs featuring button mutexes and multi-recording selectors."""
    with ui.row().classes('w-full gap-2 items-center justify-between mt-1 border-t pt-1'):
        collection_time_input = ui.number('Live-Time (s)', value=30, format='%d').props('dense outlined').classes('w-30 text-xs')
        recordings_count_input = ui.number('Recordings (Runs)', value=1, format='%d').props('dense outlined min=1').classes('w-30 text-xs')
        output_prefix_input = ui.input('Filename Prefix', value='spectrum_run').props('dense outlined').classes('flex-1 text-xs')
        
        with ui.row().classes('gap-1'):
            start_btn = ui.button('Start', icon='play_arrow', on_click=lambda: ui.timer(0.01, execute_sequenced_acquisition, once=True))
            start_btn.style(f"background-color: {BRAND_COLORS['primary']}; color: #FFFFFF;").props('dense text-color=white')
            
            stop_btn = ui.button('Stop', icon='stop', on_click=force_abort_recording)
            stop_btn.style(f"background-color: {BRAND_COLORS['crimson_trace']}; color: #FFFFFF;").props('dense text-color=white disabled')

    acquisition_progress = ui.linear_progress(value=0.0, show_value=False).classes('w-full h-1 mt-1').props('color=primary')
    status_label = ui.label('Status: Ready to acquire.').classes('text-xs font-mono text-zinc-500 q-my-none')

    async def execute_sequenced_acquisition():
        global is_recording_active
        is_recording_active = True
        
        start_btn.disable()
        stop_btn.enable()
        
        target_time = int(collection_time_input.value or 30)
        total_runs = int(recordings_count_input.value or 1)
        prefix = output_prefix_input.value or "spectrum"
        preset_ms = target_time * 1000
        
        for run_idx in range(total_runs):
            if not is_recording_active:
                break
                
            status_label.set_text(f"Status: Configuring run {run_idx + 1} of {total_runs}...")
            acquisition_progress.set_value(0.0)
            
            daq_api = DaqCommands(
                timers_preset=preset_ms, timers_c_live_time=True, timers_a_live_time=False,
                invert_pulse=system.hw_profile["invert_pulse"], tau_d=system.hw_profile["tau_d"], tau_r=system.hw_profile["tau_r"],
                shaper_s_tau_pk=system.hw_profile["shaper_s_tau_pk"], shaper_s_tau_pk_top=system.hw_profile["shaper_s_tau_pk_top"],
                vga_gain_coarse=system.hw_profile["vga_gain_coarse"], blr_s_threshold_gain=system.hw_profile["blr_s_threshold_gain"], smoothing_factor=system.hw_profile["smoothing_factor"]
            )
            daq_api.open()
            daq_api.clear_spectrum()
            daq_api.timers_reset()
            daq_api.data_acquisition_start()
            
            elapsed_seconds, last_chart_update_s = 0, 0
            while elapsed_seconds < target_time:
                if not is_recording_active:
                    daq_api.close()
                    acquisition_progress.set_value(0.0)
                    status_label.set_text("Status: Sequenced acquisition aborted. Data discarded.")
                    start_btn.enable()
                    stop_btn.disable()
                    return
                    
                await asyncio.sleep(1.0)
                timers = daq_api.timers_read()
                current_live_ms = timers["tmr_c"]
                elapsed_seconds = int(current_live_ms / 1000)
                
                acquisition_progress.set_value(min(elapsed_seconds / target_time, 1.0))
                status_label.set_text(f"Status: Run [{run_idx + 1}/{total_runs}] -> Live-Time: {elapsed_seconds}/{target_time} s")
                
                if target_time > 10 and (elapsed_seconds - last_chart_update_s) >= 10:
                    intermediate_spectrum = daq_api.read_spectrum()
                    update_interactive_plotly_canvas(system, plot_container, intermediate_spectrum)
                    last_chart_update_s = elapsed_seconds

            spectrum = daq_api.read_spectrum()
            timers_final = daq_api.timers_read()
            daq_api.close()
            
            final_live_s = timers_final["tmr_c"] / 1000.0
            final_real_s = timers_final["tmr_a"] / 1000.0
            num_channels = len(spectrum)
            vga_gain = float(system.hw_profile["vga_gain_coarse"] or 6.0)
            dc_offset_volts = -0.03  
            analyzer_offset_computed = (dc_offset_volts / 2.0) * num_channels * vga_gain
            
            session_iso_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            file_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("spectra", exist_ok=True)
            
            base_filepath = f"spectra/{file_stamp}_{system.serial_number}_{prefix}_run{run_idx:02d}"
            update_interactive_plotly_canvas(system, plot_container, spectrum)
            
            json_output = {
                "id": int(datetime.now().strftime("%Y%m%d%H%M%S")),
                "metadata": {
                    "Material type": system.runtime_metadata["Material type"], "Material form": system.runtime_metadata["Material form"],
                    "Sources": system.runtime_metadata["Sources"], "Attenuators": system.runtime_metadata["Attenuators"],
                    "Detector type": system.hw_profile["Detector type"], "Detector geometry": system.hw_profile["Detector geometry"],
                    "Detector size": system.hw_profile["Detector size"], "Detector type number": system.hw_profile["Detector type number"],
                    "Detector serial number": system.hw_profile["Detector serial number"], "Analyzer name": system.hw_profile["Analyzer name"],
                    "Analyzer serial number": system.serial_number, "Analyzer gain (keV/ch)": vga_gain, "Analyzer offset (keV)": analyzer_offset_computed,
                    "Number of channels": num_channels, "Energy calibration offset (keV)": system.hw_profile["calib_a0"], "Energy calibration linear (keV/ch)": system.hw_profile["calib_a1"],
                    "Energy calibration quadratic (keV/ch2)": system.hw_profile["calib_a2"], "Spectrum acquisition date (UTC)": session_iso_date,
                    "Spectrum real time (s)": final_real_s, "Spectrum live time (s)": final_live_s
                }, "data": spectrum
            }
            with open(f"{base_filepath}.json", "w", encoding="utf-8") as jf:
                json.dump(json_output, jf, indent=2)
            
            with open(f"{base_filepath}.spe", "w", encoding="ascii") as sf:
                sf.write(f"$SPEC_ID:\nNSIL-Det-{system.serial_number}_Run{run_idx:02d}\n")
                sf.write(f"$DATE_MEA:\n{datetime.now().strftime('%m/%d/%Y %H:%M:%S')}\n")
                sf.write(f"$MEAS_TIM:\n{final_live_s:.2f} {final_real_s:.2f}\n")
                sf.write("$SPE_REM:\n")
                sf.write(f"Sequence Run Index: {run_idx:02d}\n")
                sf.write(f"Material Type: {system.runtime_metadata['Material type']}\n")
                sf.write(f"Analyzer Offset Key: {analyzer_offset_computed:.4f} keV\n")
                sf.write(f"Analyzer Gain Key: {vga_gain:.4f} keV/ch\n")
                sf.write("$MCA_CAL:\n3\n")
                sf.write(f"{system.hw_profile['calib_a0']:.7e} {system.hw_profile['calib_a1']:.7e} {system.hw_profile['calib_a2']:.7e}\n")
                sf.write(f"$DATA:\n0 {num_channels - 1}\n")
                for counts in spectrum:
                    sf.write(f"{int(counts)}\n")
                sf.write("$ENDRECORD:\n")

        is_recording_active = False
        status_label.set_text("Status: Sequenced measurements finished successfully.")
        start_btn.enable()
        stop_btn.disable()
        ui.notify("All records exported successfully!", type="positive", color='#B8BE54')
