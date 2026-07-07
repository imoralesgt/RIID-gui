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
        
        # Operational States: 'IDLE', 'BG_RECORDING', 'ACQUIRING_SURVEY'
        self.state = 'IDLE'
        self.is_hardware_available = False
        
        # Spectroscopy Array Buffers
        self.live_spectrum = []
        self.background_spectrum = []  
        
        # Count and Hysteresis Thresholds
        self.min_counts_trigger = 2000    
        self.max_counts_limit = 15000     
        
        # Runtime Telemetry Data Slots
        self.elapsed_seconds = 0
        self.bg_target_time = 30
        self.current_isotope_id = "Standby"
        self.status_text = "System Initialized"

        # Background server-side async worker hooks
        self._main_loop_task = None
        self._heartbeat_task = None

    async def initialize_and_probe(self):
        """Dynamically handles hardware detection during system startup."""
        try:
            self.status_text = "Probing physical MCA..."
            serial = self.system.probe_device()
            logger.info(f"Successfully mapped MCA Serial Number: {serial}")
            self.is_hardware_available = True
            self.status_text = "Hardware Connected & Ready"
        except Exception as e:
            logger.error(f"Hardware probe failed on boot: {e}")
            self.is_hardware_available = False
            self.status_text = "Hardware Disconnected"

    def start_service_loops(self):
        """Spawns perpetual server-level communication routines."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._hardware_heartbeat_loop())

    async def _hardware_heartbeat_loop(self):
        """Continuously monitors instrument connectivity updates."""
        while True:
            if self.state == 'IDLE':
                daq = DaqCommands()
                try:
                    daq.open()
                    daq.get_version()
                    daq.close()
                    self.is_hardware_available = True
                    if "Disconnected" in self.status_text or "Initialized" in self.status_text:
                        self.status_text = "Hardware Connected & Ready"
                except Exception:
                    self.is_hardware_available = False
                    self.status_text = "Hardware Disconnected"
            await asyncio.sleep(2.0)

    def start_background_recording(self, target_time: int):
        if self.state != 'IDLE':
            return
        self.bg_target_time = target_time
        self.state = 'BG_RECORDING'
        self.current_isotope_id = "Recording Background..."
        self._main_loop_task = asyncio.create_task(self._bg_recording_sequence())

    async def _bg_recording_sequence(self):
        # PASS HARDWARE PROFILE TO BACKGROUND RUN ENTRIES
        daq = DaqCommands(
            timers_preset=self.bg_target_time * 1000, 
            timers_c_live_time=True, 
            timers_a_live_time=False,
            invert_pulse=self.system.hw_profile["invert_pulse"],
            tau_d=self.system.hw_profile["tau_d"],
            tau_r=self.system.hw_profile["tau_r"],
            shaper_s_tau_pk=self.system.hw_profile["shaper_s_tau_pk"],
            shaper_s_tau_pk_top=self.system.hw_profile["shaper_s_tau_pk_top"],
            vga_gain_coarse=self.system.hw_profile["vga_gain_coarse"],
            blr_s_threshold_gain=self.system.hw_profile["blr_s_threshold_gain"],
            smoothing_factor=self.system.hw_profile["smoothing_factor"]
        )
        try:
            daq.open()
            daq.clear_spectrum()
            daq.timers_reset()
            daq.data_acquisition_start()
            
            self.elapsed_seconds = 0
            while self.elapsed_seconds < self.bg_target_time and self.state == 'BG_RECORDING':
                await asyncio.sleep(1.0)
                timers = daq.timers_read()
                self.elapsed_seconds = int(timers["tmr_c"] / 1000)
                self.live_spectrum = daq.read_spectrum()
                self.status_text = f"Recording BG: {self.elapsed_seconds}/{self.bg_target_time}s"

            if self.state == 'BG_RECORDING':
                self.background_spectrum = daq.read_spectrum()
                self.status_text = "Background Profile Ready"
                self.current_isotope_id = "BG Complete. Ready for Survey."
                self.state = 'IDLE'
        except Exception as e:
            self.status_text = f"BG Error: {e}"
            self.state = 'IDLE'
        finally:
            try: daq.close() 
            except: pass

    def start_continuous_survey(self):
        if self.state != 'IDLE':
            return
        self.state = 'ACQUIRING_SURVEY'
        self.current_isotope_id = "Accumulating Counts..."
        self._main_loop_task = asyncio.create_task(self._continuous_survey_sequence())

    async def _continuous_survey_sequence(self):
        # PASS HARDWARE PROFILE TO CONTINUOUS SURVEY RUN ENTRIES
        daq = DaqCommands(
            timers_preset=self.max_counts_limit, 
            timers_c_live_time=True, 
            timers_a_live_time=False,
            invert_pulse=self.system.hw_profile["invert_pulse"],
            tau_d=self.system.hw_profile["tau_d"],
            tau_r=self.system.hw_profile["tau_r"],
            shaper_s_tau_pk=self.system.hw_profile["shaper_s_tau_pk"],
            shaper_s_tau_pk_top=self.system.hw_profile["shaper_s_tau_pk_top"],
            vga_gain_coarse=self.system.hw_profile["vga_gain_coarse"],
            blr_s_threshold_gain=self.system.hw_profile["blr_s_threshold_gain"],
            smoothing_factor=self.system.hw_profile["smoothing_factor"]
        )
        try:
            daq.open()
            daq.clear_spectrum()
            daq.timers_reset()
            daq.data_acquisition_start()

            while self.state == 'ACQUIRING_SURVEY':
                await asyncio.sleep(1.0)
                self.live_spectrum = daq.read_spectrum()
                total_counts = sum(self.live_spectrum)
                self.status_text = f"Survey Active. Total Counts: {total_counts}"

                if total_counts >= self.max_counts_limit:
                    logger.info("Hysteresis Max limit reached. Resetting buffer.")
                    daq.clear_spectrum()
                    daq.timers_reset()
                    self.current_isotope_id = "Buffer Reset. Re-accumulating..."
                    continue

                if total_counts >= self.min_counts_trigger:
                    self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum)
                else:
                    self.current_isotope_id = f"Accumulating ({total_counts}/{self.min_counts_trigger} cts)"

        except Exception as e:
            self.status_text = f"Survey Error: {e}"
            self.state = 'IDLE'
        finally:
            try: daq.close()
            except: pass

    def _execute_ml_pipeline(self, raw_spectrum: list) -> str:
        """ML Core implementation hook."""
        return "ML Outcome: Co-60 Identified"

    def stop_execution(self):
        self.state = 'IDLE'
        self.status_text = "Halted by Operator"
        self.current_isotope_id = "Standby"
        if self._main_loop_task:
            self._main_loop_task.cancel()

    def reset_service_state(self):
        self.stop_execution()
        self.live_spectrum = []
        self.background_spectrum = []
        self.status_text = "System Cleared & Reset"
        self.current_isotope_id = "Standby"
