import os
import json
import asyncio
from datetime import datetime
from config import logger
from core.daq_commands import DaqCommands
from state_engine import SpectrumAcquisitionSystem

class RIIDCoreService:
    def __init__(self):
        self.system = SpectrumAcquisitionSystem()
        
        # RUN AN IMMEDIATE BASELINE INITIALIZATION PASSTHROUGH 
        # Forces system properties out of json dictionary file before device probe completes
        self.system.sync_hardware_profile()
        
        # Operational States
        self.state = 'IDLE'
        self.is_hardware_available = False
        
        self.live_spectrum = []
        self.background_spectrum = []  
        self.batch_spectrum = [] 
        
        self.min_counts_trigger = 2000    
        self.max_counts_limit = 15000     
        
        self.batch_target_time = 30
        self.batch_total_runs = 1
        self.batch_current_run = 0
        self.batch_elapsed_seconds = 0
        self.batch_prefix = "spectrum_run"
        self.batch_status_text = "Ready to acquire file records."
        
        self.elapsed_seconds = 0
        self.bg_target_time = 30
        self.current_isotope_id = "Standby"
        self.status_text = "System Initialized"

        self._main_loop_task = None
        self._heartbeat_task = None
    async def initialize_and_probe(self):
        """Dynamically probes instrument and immediately pulls matching database slopes."""
        try:
            self.status_text = "Probing physical MCA..."
            serial = self.system.probe_device()
            
            # RE-RUN COMPILATION PROFILE SYNC LINK
            # Updates active RAM metrics to match detectors.json (e.g. "210328BE3DC9B")
            self.system.sync_hardware_profile()
            
            logger.info(f"Successfully mapped MCA Serial Number: {serial}")
            self.is_hardware_available = True
            self.status_text = "Hardware Connected & Ready"
        except Exception as e:
            logger.error(f"Hardware probe failed on boot: {e}")
            self.is_hardware_available = False
            self.status_text = "Hardware Disconnected"
            # Fallback to safety standby profile keys mapping
            self.system.sync_hardware_profile()

    def start_service_loops(self):
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._hardware_heartbeat_loop())

    async def _hardware_heartbeat_loop(self):
        while True:
            if self.state == 'IDLE':
                daq = DaqCommands()
                try:
                    daq.open(); daq.get_version(); daq.close()
                    self.is_hardware_available = True
                    if "Disconnected" in self.status_text or "Initialized" in self.status_text:
                        self.status_text = "Hardware Connected & Ready"
                except Exception:
                    self.is_hardware_available = False
                    self.status_text = "Hardware Disconnected"
            await asyncio.sleep(2.0)

    def start_background_recording(self, target_time: int):
        if self.state != 'IDLE': return
        self.bg_target_time = target_time
        self.state = 'BG_RECORDING'
        self.current_isotope_id = "Recording Background..."
        self._main_loop_task = asyncio.create_task(self._bg_recording_sequence())

    async def _bg_recording_sequence(self):
        prof = self.system.hw_profile
        daq = DaqCommands(
            timers_preset=self.bg_target_time * 1000, timers_c_live_time=True, timers_a_live_time=False,
            invert_pulse=prof.get("invert_pulse", False), tau_d=prof.get("tau_d", 1.21e-6),
            tau_r=prof.get("tau_r", 0.206e-6), shaper_s_tau_pk=prof.get("shaper_s_tau_pk", 2.5e-6),
            shaper_s_tau_pk_top=prof.get("shaper_s_tau_pk_top", 1.0e-6), vga_gain_coarse=prof.get("vga_gain_coarse", 6.0),
            blr_s_threshold_gain=prof.get("blr_s_threshold_gain", 4.0), smoothing_factor=prof.get("smoothing_factor", 2)
        )
        try:
            daq.open(); daq.clear_spectrum(); daq.timers_reset(); daq.data_acquisition_start()
            self.elapsed_seconds = 0
            while self.elapsed_seconds < self.bg_target_time and self.state == 'BG_RECORDING':
                await asyncio.sleep(1.0)
                self.elapsed_seconds = int(daq.timers_read()["tmr_c"] / 1000)
                self.live_spectrum = daq.read_spectrum()
                self.status_text = f"Recording BG: {self.elapsed_seconds}/{self.bg_target_time}s"
            if self.state == 'BG_RECORDING':
                self.background_spectrum = daq.read_spectrum()
                self.status_text = "Background Profile Ready"
                self.current_isotope_id = "BG Complete. Ready for Survey."
                self.state = 'IDLE'
        except Exception as e:
            self.status_text = f"BG Error: {e}"; self.state = 'IDLE'
        finally:
            try: daq.close()
            except: pass
    def start_continuous_survey(self):
        if self.state != 'IDLE': return
        self.state = 'ACQUIRING_SURVEY'
        self.current_isotope_id = "Accumulating Counts..."
        self._main_loop_task = asyncio.create_task(self._continuous_survey_sequence())

    async def _continuous_survey_sequence(self):
        prof = self.system.hw_profile
        daq = DaqCommands(
            timers_preset=self.max_counts_limit, timers_c_live_time=True, timers_a_live_time=False,
            invert_pulse=prof.get("invert_pulse", False), tau_d=prof.get("tau_d", 1.21e-6),
            tau_r=prof.get("tau_r", 0.206e-6), shaper_s_tau_pk=prof.get("shaper_s_tau_pk", 2.5e-6),
            shaper_s_tau_pk_top=prof.get("shaper_s_tau_pk_top", 1.0e-6), vga_gain_coarse=prof.get("vga_gain_coarse", 6.0),
            blr_s_threshold_gain=prof.get("blr_s_threshold_gain", 4.0), smoothing_factor=prof.get("smoothing_factor", 2)
        )
        try:
            daq.open(); daq.clear_spectrum(); daq.timers_reset(); daq.data_acquisition_start()
            while self.state == 'ACQUIRING_SURVEY':
                await asyncio.sleep(1.0)
                self.live_spectrum = daq.read_spectrum()
                total_counts = sum(self.live_spectrum)
                self.status_text = f"Survey Active. Total Counts: {total_counts}"
                if total_counts >= self.max_counts_limit:
                    daq.clear_spectrum(); daq.timers_reset()
                    self.current_isotope_id = "Buffer Reset. Re-accumulating..."
                    continue
                if total_counts >= self.min_counts_trigger:
                    self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum)
                else:
                    self.current_isotope_id = f"Accumulating ({total_counts}/{self.min_counts_trigger} cts)"
        except Exception as e:
            self.status_text = f"Survey Error: {e}"; self.state = 'IDLE'
        finally:
            try: daq.close()
            except: pass

    def _execute_ml_pipeline(self, raw_spectrum: list) -> str:
        return "ML Outcome: Co-60 Identified"

    def start_batch_recording(self, target_time: int, total_runs: int, prefix: str):
        if self.state != 'IDLE': return
        self.batch_target_time = target_time; self.batch_total_runs = total_runs; self.batch_prefix = prefix
        self.state = 'BATCH_RECORDING'
        self._main_loop_task = asyncio.create_task(self._batch_recording_worker_loop())

    async def _batch_recording_worker_loop(self):
        for run_idx in range(self.batch_total_runs):
            if self.state != 'BATCH_RECORDING': break
            self.batch_current_run = run_idx + 1
            self.batch_status_text = f"Configuring run {self.batch_current_run} of {self.batch_total_runs}..."
            self.batch_elapsed_seconds = 0
            prof = self.system.hw_profile
            daq_api = DaqCommands(
                timers_preset=self.batch_target_time * 1000, timers_c_live_time=True, timers_a_live_time=False,
                invert_pulse=prof.get("invert_pulse", False), tau_d=prof.get("tau_d", 1.21e-6),
                tau_r=prof.get("tau_r", 0.206e-6), shaper_s_tau_pk=prof.get("shaper_s_tau_pk", 2.5e-6),
                shaper_s_tau_pk_top=prof.get("shaper_s_tau_pk_top", 1.0e-6), vga_gain_coarse=prof.get("vga_gain_coarse", 6.0),
                blr_s_threshold_gain=prof.get("blr_s_threshold_gain", 4.0), smoothing_factor=prof.get("smoothing_factor", 2)
            )
            try:
                daq_api.open(); daq_api.clear_spectrum(); daq_api.timers_reset(); daq_api.data_acquisition_start()
            except Exception as e:
                self.batch_status_text = f"Hardware error: {e}"; break
            while self.batch_elapsed_seconds < self.batch_target_time and self.state == 'BATCH_RECORDING':
                await asyncio.sleep(1.0)
                self.batch_elapsed_seconds = int(daq_api.timers_read()["tmr_c"] / 1000)
                self.batch_spectrum = daq_api.read_spectrum()
                self.batch_status_text = f"Run [{self.batch_current_run}/{self.batch_total_runs}] -> Live-Time: {self.batch_elapsed_seconds}/{self.batch_target_time}s"
            if self.state != 'BATCH_RECORDING': daq_api.close(); return
            final_spectrum = daq_api.read_spectrum(); timers_final = daq_api.timers_read(); daq_api.close()
            time_now = datetime.now(); os.makedirs("spectra", exist_ok=True); file_stamp = time_now.strftime("%Y%m%d_%H%M%S")
            base_filepath = f"spectra/{file_stamp}_{self.system.serial_number}_{self.batch_prefix}_run{run_idx:04d}"
            with open(f"{base_filepath}.json", "w", encoding="utf-8") as jf:
                json.dump({"id": f"RUN_{run_idx}", "metadata": self.system.runtime_metadata, "data": final_spectrum}, jf, indent=2)
        self.state = 'IDLE'; self.batch_status_text = "Batch measurements finished successfully."

    def stop_execution(self):
        self.state = 'IDLE'; self.status_text = "Halted by Operator"; self.batch_status_text = "Halted by Operator"; self.current_isotope_id = "Standby"
        if self._main_loop_task: self._main_loop_task.cancel()

    def reset_service_state(self):
        self.stop_execution(); self.live_spectrum = []; self.batch_spectrum = []; self.background_spectrum = []
        self.status_text = "System Cleared & Reset"; self.batch_status_text = "Ready to acquire file records."; self.current_isotope_id = "Standby"
