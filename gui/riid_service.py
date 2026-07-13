import os
import json
import asyncio
from datetime import datetime
from config import logger, DATA_DIR
from core.daq_commands import DaqCommands
from state_engine import SpectrumAcquisitionSystem

class RIIDCoreService:
    # Centralized folder destination constant
    OUTPUT_FOLDER = DATA_DIR

    # Programmatic class constant for the unsigned 32-bit hardware register gating limit (2^32 - 1)
    MAX_32BIT_UINT = int(2**32 - 1)

    def __init__(self):
        logger.info("[SERVICE_INIT] Initializing spectroscopy operations hub...")
        self.system = SpectrumAcquisitionSystem()
        self.system.sync_hardware_profile()
        
        # Shared authoritative singleton hardware controller instance anchor
        self.daq_device = None
        
        # Operational State Flags
        self.state = 'IDLE'
        self.is_hardware_available = False
        
        # Dynamic Spectrum Vector Storage Buffers
        self.live_spectrum = []
        self.background_spectrum = []  
        self.batch_spectrum = [] 
        
        # Trigger thresholds for automated identification pipelines
        self.min_counts_trigger = 2000    
        self.max_counts_limit = 15000     
        
        # Configuration presets for structural automated multi-run recordings
        self.batch_target_time = 30
        self.batch_total_runs = 1
        self.batch_current_run = 0
        self.batch_elapsed_seconds = 0
        self.batch_prefix = "spectrum_run"
        self.batch_status_text = "Ready to acquire file records."
        
        # Live display state fields
        self.elapsed_seconds = 0
        self.bg_target_time = 30
        self.bg_accumulated_seconds = 0
        self.survey_elapsed_seconds = 0
        self.bg_progress = 0.0
        
        self.current_isotope_id = "Standby"
        self.status_text = "System Initialized"
        
        # Interlock safety configuration tracking flags
        self.hardware_sync_required = True  

        # Asynchronous Task Tracking Handles
        self._main_loop_task = None
        self._heartbeat_task = None

    def reinitialize_daq_handle(self, explicit_preset_ms: int = 0):
        """Safely destroys any stale tracking references and instantiates a clean driver mapping the JSON profile."""
        prof = self.system.hw_profile
        logger.info(f"[SERVICE] Re-initializing master driver wrapper handle. Target Preset: {explicit_preset_ms} ms")
        
        if self.daq_device is not None:
            try:
                self.daq_device.close()
            except:
                pass
            self.daq_device = None
            
        # Explicitly pass configuration parameters straight into the initialization constructor context
        self.daq_device = DaqCommands(
            timers_preset=explicit_preset_ms,
            timers_c_live_time=True,
            timers_a_live_time=False,
            invert_pulse=prof.get("invert_pulse", False),
            tau_d=prof.get("tau_d", 1.21e-6),
            tau_r=prof.get("tau_r", 0.206e-6),
            shaper_s_tau_pk=prof.get("shaper_s_tau_pk", 2.5e-6),
            shaper_s_tau_pk_top=prof.get("shaper_s_tau_pk_top", 1.0e-6),
            vga_gain_coarse=prof.get("vga_gain_coarse", 6.0),
            blr_s_threshold_gain=prof.get("blr_s_threshold_gain", 4.0),
            smoothing_factor=prof.get("smoothing_factor", 2)
        )

    def push_active_profile_to_board(self):
        """Pushes user calibration parameter adjustments down to the board via the persistent handle."""
        if not self.is_hardware_available:
            logger.warning("[SERVICE] Target board offline. Parameter programming bypassed.")
            return

        logger.info("[MCA_PROG] Broadcasting parameter block matrix down to board submodules...")
        try:
            self.reinitialize_daq_handle(explicit_preset_ms=0)
            self.daq_device.open()
            self.daq_device.close()
            self.hardware_sync_required = False
        except Exception as e:
            logger.error(f"[MCA_PROG] Master parameter injection failed: {e}", exc_info=True)
    async def initialize_and_probe(self):
        """Asynchronously discovers hardware on startup sequence."""
        logger.info("[SERVICE] Executing physical hardware device inquiry sweep...")
        try:
            self.status_text = "Probing physical MCA..."
            serial_no = await asyncio.to_thread(self.system.probe_device)
            logger.info(f"[SERVICE] Discovery successful. Serial profile: {serial_no}")
            self.is_hardware_available = True
            self.status_text = "Hardware Connected & Ready"
            
            self.push_active_profile_to_board()
        except Exception as e:
            logger.error(f"[SERVICE] Connection inquiry failed on boot: {e}", exc_info=True)
            self.is_hardware_available = False
            self.status_text = "Hardware Disconnected"
            self.system.sync_hardware_profile()

    def start_service_loops(self):
        """Spawns long-running async background monitor workers."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._hardware_heartbeat_loop())

    async def _hardware_heartbeat_loop(self):
        """Monitors system connection topology natively without disrupting the master API driver context."""
        logger.info("[HEARTBEAT] Asynchronous non-invasive serial monitor online.")
        while True:
            if self.state == 'IDLE':
                target_port = self.system.hw_profile.get("port_name")
                if target_port is None and self.system.serial_number != "UNKNOWN":
                    if os.path.exists("/dev/ttyUSB1"): target_port = "/dev/ttyUSB1"
                    elif os.path.exists("/dev/ttyUSB0"): target_port = "/dev/ttyUSB0"
                    if target_port: self.system.hw_profile["port_name"] = target_port

                if not self.is_hardware_available:
                    try:
                        logger.warning("[HEARTBEAT] Hardware link missing. Running re-probe discovery sequence...")
                        await asyncio.to_thread(self.system.probe_device)
                        self.is_hardware_available = True
                        self.status_text = "Hardware Connected & Ready"
                        self.hardware_sync_required = True
                        logger.info(f"[HEARTBEAT] Reconnection recovery successful. Node S/N: {self.system.serial_number}")
                    except:
                        self.is_hardware_available = False
                        self.status_text = "Hardware Disconnected"
                else:
                    port_to_check = target_port if target_port else "/dev/ttyUSB1"
                    if os.path.exists(port_to_check):
                        self.is_hardware_available = True
                        if "Disconnected" in self.status_text:
                            self.status_text = "Hardware Connected & Ready"
                    else:
                        logger.error(f"[HEARTBEAT] Physical device disconnected from port location: {port_to_check}")
                        self.is_hardware_available = False
                        self.status_text = "Hardware Disconnected"
                        self.system.serial_number = "UNKNOWN"
            await asyncio.sleep(1.0)

    def start_background_recording(self, target_time: int):
        """Spawns background spectrum profiling worker task and purges stale arrays."""
        logger.info(f"[DAQ_ACTION] Operator initiated background spectrum profiling run ({target_time}s)...")
        if self.state != 'IDLE': 
            logger.warning(f"[DAQ_ACTION] Background start rejected. Core state is busy: {self.state}")
            return
            
        self.background_spectrum = []
        self.live_spectrum = []
        self.bg_target_time = target_time
        self.state = 'BG_RECORDING'
        self.current_isotope_id = "Recording Background..."
        self._main_loop_task = asyncio.create_task(self._bg_recording_sequence())

    async def _bg_recording_sequence(self):
        """Asynchronous worker for collecting background spectrum matrix arrays with accurate hardware live-time capture."""
        logger.info("[BACKGROUND_RUN] Async recording pipeline workers mounting...")
        try:
            self.reinitialize_daq_handle(explicit_preset_ms=self.bg_target_time * 1000)
            self.daq_device.open()
            self.daq_device.clear_spectrum()
            self.daq_device.timers_reset()
            self.daq_device.data_acquisition_start()
            
            self.elapsed_seconds = 0
            self.bg_progress = 0.0
            
            while self.elapsed_seconds < self.bg_target_time and self.state == 'BG_RECORDING':
                await asyncio.sleep(1.0)
                if not self.verify_runtime_hardware_safety():
                    break
                    
                # Read hardware timers dynamically
                hw_timers = self.daq_device.timers_read()
                self.elapsed_seconds = int(hw_timers.get("tmr_c", 0) / 1000)
                self.live_spectrum = self.daq_device.read_spectrum()
                self.bg_progress = min(float(self.elapsed_seconds / self.bg_target_time), 1.0) if self.bg_target_time > 0 else 1.0
                self.status_text = f"Recording BG: {self.elapsed_seconds}/{self.bg_target_time}s"
                
            if self.state == 'BG_RECORDING':
                self.background_spectrum = self.daq_device.read_spectrum()
                
                # FIXED: Extract final absolute background hardware live-time directly from the MCA registers
                final_bg_timers = self.daq_device.timers_read()
                self.bg_hardware_live_time_ms = float(final_bg_timers.get("tmr_c", self.bg_target_time * 1000))
                self.bg_accumulated_seconds = int(self.bg_hardware_live_time_ms / 1000)
                
                self.bg_progress = 1.0
                self.status_text = "Background Profile Ready"
                self.current_isotope_id = "BG Complete. Ready for Survey."
                self.state = 'IDLE'
                logger.info(f"[BACKGROUND_RUN] Background profile saved. Pure HW Live-Time: {self.bg_hardware_live_time_ms} ms")
        except Exception as e:
            logger.error(f"[BACKGROUND_RUN] Pipeline error: {e}", exc_info=True)
            self.status_text = f"BG Error: {e}"; self.state = 'IDLE'; self.bg_progress = 0.0
        finally:
            try: self.daq_device.close()
            except: pass


    def start_continuous_survey(self):
        """Launches continuous acquisition tracks utilizing pure hardware accumulation registers."""
        logger.info("[SERVICE] Operator initiated continuous radioisotope identification survey loop...")
        if self.state != 'IDLE': return
        
        self.live_spectrum = []
        self.survey_elapsed_seconds = 0
        self.state = 'ACQUIRING_SURVEY'
        self.current_isotope_id = "Accumulating Counts..."
        self._main_loop_task = asyncio.create_task(self._continuous_survey_sequence())

    async def _continuous_survey_sequence(self):
        """Asynchronous execution task interacting safely through open-ended constructor parameters initialization with exact HW timers."""
        logger.info("[SURVEY_RUN] Shared master API channel activated for live collection.")
        try:
            self.reinitialize_daq_handle(explicit_preset_ms=self.MAX_32BIT_UINT)
            
            self.daq_device.open()
            self.daq_device.clear_spectrum()
            self.daq_device.timers_reset()
            self.daq_device.data_acquisition_start()
            
            self.survey_elapsed_seconds = 0
            # Initialize live survey hardware timer tracking metrics fields
            self.survey_hardware_live_time_ms = 0.0
            
            logger.info("[SURVEY_RUN] MCA board successfully programmed and verified via bus command.")
            
            while self.state == 'ACQUIRING_SURVEY':
                await asyncio.sleep(1.0)
                if not self.verify_runtime_hardware_safety():
                    break
                
                # FIXED: Read hardware live-time straight from the active survey session registers
                survey_timers = self.daq_device.timers_read()
                self.survey_hardware_live_time_ms = float(survey_timers.get("tmr_c", 0))
                self.survey_elapsed_seconds = int(self.survey_hardware_live_time_ms / 1000)
                
                hardware_spectrum_array = self.daq_device.read_spectrum()
                if hardware_spectrum_array:
                    self.live_spectrum = hardware_spectrum_array
                    
                total_counts = sum(self.live_spectrum) if self.live_spectrum else 0
                self.status_text = f"Survey Active ({self.survey_elapsed_seconds}s). Total Counts: {total_counts}"
                
                if total_counts >= self.max_counts_limit:
                    logger.warning(f"[SURVEY_RUN] Counts [{total_counts}] hit ceiling [{self.max_counts_limit}]. Resetting hardware...")
                    
                    try: self.daq_device.data_acquisition_stop()
                    except: pass
                    
                    self.daq_device.clear_spectrum()
                    self.daq_device.timers_reset()
                    
                    self.reinitialize_daq_handle(explicit_preset_ms=self.MAX_32BIT_UINT)
                    self.daq_device.open()
                    self.daq_device.data_acquisition_start()
                    
                    self.survey_elapsed_seconds = 0
                    self.survey_hardware_live_time_ms = 0.0
                    self.current_isotope_id = "Buffer Reset. Re-accumulating..."
                    continue
                
                if total_counts >= self.min_counts_trigger:
                    self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum)
                else:
                    self.current_isotope_id = f"Accumulating ({total_counts}/{self.min_counts_trigger} cts)"
                    
            try: self.daq_device.data_acquisition_stop()
            except: pass
        except Exception as e:
            logger.error(f"[HARDWARE] Continuous survey thread encountered an exception: {e}", exc_info=True)
            self.status_text = f"Survey Error: {e}"; self.state = 'IDLE'
        finally:
            try: self.daq_device.close()
            except: pass
            logger.info("[SURVEY_RUN] Shared master loop context released safely.")


    def _execute_ml_pipeline(self, raw_spectrum: list) -> str:
        """Mock placeholder representing automated isotope identification algorithm model."""
        return "ML Outcome: Co-60 Identified"

    def start_batch_recording(self, target_time: int, total_runs: int, prefix: str):
        """Assembles automated structural script loops mapping data files."""
        logger.warning(f"[DAQ_ACTION] Operator triggered automated multi-run batch recording -> runs={total_runs}")
        if self.state != 'IDLE': return
        self.batch_target_time = target_time; self.batch_total_runs = total_runs; self.batch_prefix = prefix
        self.state = 'BATCH_RECORDING'
        self._main_loop_task = asyncio.create_task(self._batch_recording_worker_loop())

    async def _batch_recording_worker_loop(self):
        """Automated file system serialization thread worker array loop."""
        for run_idx in range(self.batch_total_runs):
            if self.state != 'BATCH_RECORDING': break
            self.batch_current_run = run_idx + 1
            logger.info(f"[BATCH_WORKER] Arranging sequence trace run [{self.batch_current_run}/{self.batch_total_runs}]...")
            self.batch_status_text = f"Configuring run {self.batch_current_run} of {self.batch_total_runs}..."
            self.batch_elapsed_seconds = 0
            
            # Dynamically map profile configuration values here during automated multi-run batches too
            self.reinitialize_daq_handle(explicit_preset_ms=self.batch_target_time * 1000)
            
            try:
                self.daq_device.open(); self.daq_device.clear_spectrum(); self.daq_device.timers_reset(); self.daq_device.data_acquisition_start()
            except Exception as e:
                logger.error(f"[BATCH_WORKER] Hardware access dropped during sequence initiation step: {e}", exc_info=True)
                self.batch_status_text = f"Hardware error: {e}"; break
                
            while self.batch_elapsed_seconds < self.batch_target_time and self.state == 'BATCH_RECORDING':
                await asyncio.sleep(1.0)
                if not self.verify_runtime_hardware_safety(): break
                self.batch_elapsed_seconds = int(self.daq_device.timers_read()["tmr_c"] / 1000)
                self.batch_spectrum = self.daq_device.read_spectrum()
                self.batch_status_text = f"Run [{self.batch_current_run}/{self.batch_total_runs}] -> Live-Time: {self.batch_elapsed_seconds}/{self.batch_target_time}s"
                
            if self.state != 'BATCH_RECORDING': 
                try: self.daq_device.close()
                except: pass
                return
                
            final_spectrum = self.daq_device.read_spectrum(); self.daq_device.close()
            
            time_now = datetime.now()
            os.makedirs(self.OUTPUT_FOLDER, exist_ok=True)
            file_stamp = time_now.strftime("%Y%m%d_%H%M%S")
            base_filepath = os.path.join(self.OUTPUT_FOLDER, f"{file_stamp}_{self.system.serial_number}_{self.batch_prefix}_run{run_idx:04d}")
            
            logger.info(f"[BATCH_WORKER] Committing spectrum array json to root: {base_filepath}.json")
            with open(f"{base_filepath}.json", "w", encoding="utf-8") as jf:
                json.dump({"id": f"RUN_{run_idx}", "metadata": self.system.runtime_metadata, "data": final_spectrum}, jf, indent=2)
                
        self.state = 'IDLE'; self.batch_status_text = "Batch measurements finished successfully."

    def stop_execution(self):
        """Forces runtime processing threads to drop cleanly."""
        logger.warning(f"[SERVICE] Operator pressed STOP button. Forcing immediate pipeline cancellation out of state: {self.state}")
        self.state = 'IDLE'; self.status_text = "Halted by Operator"; self.batch_status_text = "Halted by Operator"; self.current_isotope_id = "Standby"
        if self._main_loop_task: self._main_loop_task.cancel()

    def reset_service_state(self):
        """Wipes transient memory traces."""
        logger.info("[SERVICE] Operator requested clear and factory calibration state memory purge.")
        self.stop_execution(); self.live_spectrum = []; self.batch_spectrum = []; self.background_spectrum = []
        self.status_text = "System Cleared & Reset"; self.batch_status_text = "Ready to acquire file records."; self.current_isotope_id = "Standby"

    def verify_runtime_hardware_safety(self) -> bool:
        """Validates live connectivity during active data collection runs. Auto-halts on failure."""
        if not self.is_hardware_available:
            logger.critical("[ACQUISITION_GUARD] Live physical device connection lost mid-run! Intercepting crash...")
            self.state = 'IDLE'
            self.status_text = "CRITICAL: Device Disconnected Mid-Run"
            self.batch_status_text = "CRITICAL: Run aborted due to hardware loss."
            self.current_isotope_id = "Hardware Lost"
            if self._main_loop_task and not self._main_loop_task.done():
                self._main_loop_task.cancel()
            return False
        return True
