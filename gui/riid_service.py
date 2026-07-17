import os
import json
import asyncio
from datetime import datetime
from config import logger, DATA_DIR
from core.daq_commands import DaqCommands
from core.daq_constants import DppSubmodules
from core.dpp_parameters import Dpp_Timers
from state_engine import SpectrumAcquisitionSystem
from ml_inference import MlInference

class RIIDCoreService:
    # Centralized folder destination constant
    OUTPUT_FOLDER = DATA_DIR

    # Programmatic class constant for the unsigned 32-bit hardware register gating limit (2^32 - 1)
    MAX_32BIT_UINT = int(2**32 - 1)

    def __init__(self, ml_model_name : str):
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
        
        # Tracks whether the last survey was halted by the operator (STOP) while
        # holding valid spectrum data, so the plot can keep rendering it "frozen"
        # instead of disappearing once the state leaves ACQUIRING_SURVEY.
        self.survey_stopped_with_data = False
        
        # Set by clear_survey_data() while a survey is actively running; the
        # acquisition loop polls this flag and performs the actual hardware-level
        # reset on its own next tick, so CLEAR works without requiring STOP first.
        self.clear_requested = False
        
        # Asynchronous Task Tracking Handles
        self._main_loop_task = None
        self._heartbeat_task = None

        # ML inference model
        self.ml_inference = MlInference(ml_model_name = ml_model_name, min_counts = 20)

    def reinitialize_daq_handle(self):
        """Destroys any stale driver reference and instantiates a fresh one, transmitting
        the CURRENT calibration/DPP profile (tau_d, tau_r, shaper timings, VGA gain, BLR
        threshold, smoothing, invert-pulse) to the board via the constructor.
        
        IMPORTANT: this is the only place DPP parameters are ever sent to the hardware,
        and it must only be called from push_active_profile_to_board() - i.e. on initial
        hardware probe (app/service launch) or an explicit calibration commit. Routine
        survey/background/batch START presses must reuse the already-programmed
        self.daq_device handle instead of calling this, so the board's own on-chip
        accumulation registers are never disturbed by a config resend.
        
        The timers_preset is fixed at the unsigned-32-bit ceiling (effectively unlimited)
        for every operation - background and batch recordings already enforce their own
        exact duration purely in software by polling elapsed hardware live-time, so no
        per-operation preset needs to be (re)programmed here."""
        prof = self.system.hw_profile
        logger.info("[SERVICE] Re-initializing master driver wrapper handle with current DPP profile.")
        
        if self.daq_device is not None:
            try:
                self.daq_device.close()
            except:
                pass
            self.daq_device = None
            
        # Explicitly pass configuration parameters straight into the initialization constructor context
        self.daq_device = DaqCommands(
            timers_preset=self.MAX_32BIT_UINT,
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

    def push_active_profile_to_board(self) -> bool:
        """Programs the current calibration/DPP parameters onto the physical board.
        
        This is invoked ONLY under two conditions:
          1. The app/service is launched for the first time (see initialize_and_probe).
          2. The operator presses COMMIT CALIBRATION PARAMETERS (see view_calibration.py).
        (A hardware reconnect after a physical disconnect is treated the same as an
        initial probe, since the board's configuration is assumed lost on power-cycle -
        see _hardware_heartbeat_loop.)
        
        Every other acquisition entry point (survey/background/batch START) intentionally
        does NOT call this, so the board's on-chip spectrum accumulation is left completely
        undisturbed across ordinary STOP -> START cycles.
        
        Returns True on success, False if programming was skipped or failed."""
        if not self.is_hardware_available:
            logger.warning("[SERVICE] Target board offline. Parameter programming bypassed.")
            return False
        if self.state != 'IDLE':
            logger.warning(f"[SERVICE] Parameter programming deferred - acquisition busy ({self.state}).")
            return False

        logger.info("[MCA_PROG] Broadcasting parameter block matrix down to board submodules...")
        try:
            self.reinitialize_daq_handle()
            self.daq_device.open()
            # A freshly-programmed board implies a freshly-cleared accumulator; keep the
            # on-chip registers and the software-side survey bookkeeping in sync.
            self.daq_device.clear_spectrum()
            self.daq_device.timers_reset()
            self.daq_device.close()
            
            self.live_spectrum = []
            self.survey_elapsed_seconds = 0
            self.survey_hardware_live_time_ms = 0.0
            self.survey_stopped_with_data = False
            return True
        except Exception as e:
            logger.error(f"[MCA_PROG] Master parameter injection failed: {e}", exc_info=True)
            return False

    def _set_timers_preset(self, preset_ms: int) -> bool:
        """Updates ONLY the Timers DPP submodule (group 4, which holds the Preset
        register tied to Timer C) on the ALREADY-programmed board handle, so a
        survey/background/batch run can configure its exact millisecond collection
        window on the hardware's own clock.
        
        This deliberately does NOT go through reinitialize_daq_handle() / recreate
        self.daq_device - doing so would resend every other DPP submodule (shaper,
        gain, BLR, etc.), which is reserved for push_active_profile_to_board() only
        (hardware probe / an explicit calibration commit). DaqCommands.set_dpp_params()
        transmits just the one submodule group requested, leaving everything else on
        the board untouched.
        
        The live/real-time flags mirror what reinitialize_daq_handle() already
        configures (Timer C = live time, Timer A = real time) so this doesn't
        silently change timer semantics - only the Preset value itself.
        
        Returns True on success, False if there's no programmed handle or the
        transmission failed (callers should fall back to pure software timing)."""
        if self.daq_device is None:
            logger.warning("[SERVICE] Cannot set timer preset - no programmed device handle available.")
            return False
        try:
            self.daq_device.dpp.timers = Dpp_Timers(
                tmr_preset_time=preset_ms,
                tmr_c_lt=True,
                tmr_a_lt=False,
            )
            self.daq_device.set_dpp_params(DppSubmodules.TIMERS)
            logger.info(f"[SERVICE] Timer preset updated to {preset_ms} ms (Timers submodule only, no other DPP groups resent).")
            return True
        except Exception as e:
            logger.error(f"[SERVICE] Failed to set timer preset: {e}", exc_info=True)
            return False

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
                        # Treated as equivalent to an initial probe: the board's config is
                        # assumed lost across a physical disconnect, so it must be reprogrammed.
                        self.push_active_profile_to_board()
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
        """Asynchronous worker for collecting background spectrum matrix arrays with accurate hardware live-time capture.
        Reuses the already-programmed device handle (see push_active_profile_to_board) -
        no DPP parameters are resent here. The on-board register clear below is specific
        to starting a fresh background capture and is unrelated to DPP programming."""
        logger.info("[BACKGROUND_RUN] Async recording pipeline worker mounting...")
        if self.daq_device is None:
            logger.error("[BACKGROUND_RUN] No programmed device handle available. Was the board ever probed/calibrated?")
            self.status_text = "BG Error: Board not programmed"; self.state = 'IDLE'
            return
        
        # Give the board's own clock millisecond-precision control over when Timer C
        # (live time) stops, matching this run's requested duration. Falls back to
        # pure software timing (with some overshoot) if this can't be set.
        if not self._set_timers_preset(self.bg_target_time * 1000):
            logger.warning("[BACKGROUND_RUN] Hardware timer preset could not be set - falling back to software-only timing.")
        
        try:
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

                # Update ML model background
                self.ml_inference.update_bkgnd_data(new_bkgnd_data=self.background_spectrum, new_bkgnd_live_time=self.bg_accumulated_seconds)

                logger.info(f"[BACKGROUND_RUN] Background profile saved. Pure HW Live-Time: {self.bg_hardware_live_time_ms} ms")
        except Exception as e:
            logger.error(f"[BACKGROUND_RUN] Pipeline error: {e}", exc_info=True)
            self.status_text = f"BG Error: {e}"; self.state = 'IDLE'; self.bg_progress = 0.0
        finally:
            # Runs on every exit path - normal completion, an error above, or an
            # aborted run (STOP pressed mid-BG, hardware lost, task cancelled).
            # Without this, the hardware keeps silently accumulating counts (and
            # Timer C keeps ticking) after a BG run ends, and self.live_spectrum -
            # only ever meant as a live-display side-channel during THIS BG run -
            # would be left behind for the next survey START to mistake for a
            # prior survey accumulation to resume (the actual cause of the survey's
            # first frame showing the just-recorded background spectrum).
            try:
                self.daq_device.data_acquisition_stop()
                self.daq_device.clear_spectrum()
                self.daq_device.timers_reset()
            except Exception as e:
                logger.error(f"[BACKGROUND_RUN] Failed to cleanly halt/clear hardware after BG capture: {e}", exc_info=True)
            self.live_spectrum = []
            try: self.daq_device.close()
            except: pass


    def start_continuous_survey(self):
        """Launches/resumes continuous acquisition on the already-programmed device handle.
        Does NOT resend DPP parameters - true continuity across STOP -> START cycles is
        achieved by leaving the board's configuration untouched on an ordinary start.
        DPP parameters are only ever transmitted by push_active_profile_to_board()
        (hardware probe / an explicit calibration commit).
        
        Per the DPP4SiPM firmware docs, the $AQ start command (flags 0/1) unavoidably
        clears the BRAM spectrum memory as part of starting acquisition - there is no
        hardware "resume" flag. _continuous_survey_sequence() compensates for this in
        software by carrying the previously accumulated spectrum forward as a baseline
        and adding each new hardware reading on top of it. The live-time timer is NOT
        reset by $AQ 1 (only an explicit $AQ 4 / timers_reset() does that, which ordinary
        START never calls), so it already persists correctly without any extra bookkeeping."""
        logger.info("[SERVICE] Operator initiated continuous radioisotope identification survey loop...")
        if self.state != 'IDLE': return
        
        self.survey_stopped_with_data = False
        self.state = 'ACQUIRING_SURVEY'
        self.current_isotope_id = "Resuming Accumulation..." if self.live_spectrum else "Accumulating Counts..."
        self._main_loop_task = asyncio.create_task(self._continuous_survey_sequence())

    async def _continuous_survey_sequence(self):
        """Asynchronous execution task interacting safely through open-ended constructor parameters initialization with exact HW timers.
        Reuses the already-programmed device handle (see push_active_profile_to_board) -
        no DPP parameters are resent here.
        
        IMPORTANT (per DPP4SiPM firmware docs, $AQ command): calling data_acquisition_start()
        (flag 0 or 1) "Cleans BRAM contents prior to starting" as an unconditional hardware
        side effect - this happens regardless of DPP reprogramming, and there is no flag to
        resume without clearing. So the previously accumulated spectrum is captured here as
        a baseline BEFORE starting, and added back on top of every subsequent hardware
        reading, giving true continuity across STOP -> START despite the BRAM wipe.
        The on-board live-time timer (tmr_c) is untouched by $AQ 1 (only $AQ 4 /
        timers_reset() clears it, which an ordinary start never calls), so it already
        reads the correct cumulative value with no baseline math needed."""
        logger.info("[SURVEY_RUN] Shared master API channel activated for live collection.")
        if self.daq_device is None:
            logger.error("[SURVEY_RUN] No programmed device handle available. Was the board ever probed/calibrated?")
            self.status_text = "Survey Error: Board not programmed"; self.state = 'IDLE'
            return
        try:
            self.daq_device.open()
            
            # Force the hardware Preset register back to "unlimited" before every
            # survey start (fresh AND resume alike). A prior BG recording or batch
            # run leaves the board's Preset at ITS target duration (see
            # _set_timers_preset); if left unchanged, the survey would silently
            # auto-stall the instant Timer C reaches that leftover value, well
            # before the operator intends to stop. This only touches the Timers
            # DPP submodule (group 4) - it does not clear BRAM/spectrum, so it's
            # safe to call unconditionally without disturbing the resumed baseline.
            if not self._set_timers_preset(self.MAX_32BIT_UINT):
                logger.warning("[SURVEY_RUN] Could not reset timer preset to unlimited - survey may stall early if a prior BG/batch preset is still active on the board.")
            
            # Snapshot whatever was accumulated before this start - $AQ is about to wipe
            # the physical BRAM out from under us regardless of what we do here.
            baseline_spectrum = list(self.live_spectrum) if self.live_spectrum else []
            
            self.daq_device.data_acquisition_start()
            
            if baseline_spectrum:
                logger.info(f"[SURVEY_RUN] Resuming on top of {sum(baseline_spectrum)} previously accumulated counts (BRAM cleared by $AQ; live-time timer persists in hardware).")
            else:
                logger.info("[SURVEY_RUN] Resumed acquisition on existing programmed handle (no DPP resend).")
            
            while self.state == 'ACQUIRING_SURVEY':
                await asyncio.sleep(1.0)
                if not self.verify_runtime_hardware_safety():
                    break
                
                if self.clear_requested:
                    logger.warning("[SURVEY_RUN] CLEAR requested mid-survey. Resetting on-board accumulation registers without stopping the survey or resending DPP parameters...")
                    self.clear_requested = False
                    baseline_spectrum = []
                    try: self.daq_device.data_acquisition_stop()
                    except: pass
                    self.daq_device.clear_spectrum()
                    self.daq_device.timers_reset()
                    self.daq_device.data_acquisition_start()
                    self.survey_elapsed_seconds = 0
                    self.survey_hardware_live_time_ms = 0.0
                    self.live_spectrum = []
                    self.current_isotope_id = "Accumulating Counts..."
                    continue
                
                # FIXED: Read hardware live-time straight from the active survey session registers
                survey_timers = self.daq_device.timers_read()
                self.survey_hardware_live_time_ms = float(survey_timers.get("tmr_c", 0))
                self.survey_elapsed_seconds = int(self.survey_hardware_live_time_ms / 1000)
                
                hardware_spectrum_array = self.daq_device.read_spectrum()
                if hardware_spectrum_array:
                    if baseline_spectrum and len(baseline_spectrum) == len(hardware_spectrum_array):
                        self.live_spectrum = [b + h for b, h in zip(baseline_spectrum, hardware_spectrum_array)]
                    else:
                        self.live_spectrum = hardware_spectrum_array
                    
                total_counts = sum(self.live_spectrum) if self.live_spectrum else 0
                self.status_text = f"Survey Active ({self.survey_elapsed_seconds}s). Total Counts: {total_counts}"
                
                if total_counts >= self.max_counts_limit:
                    logger.warning(f"[SURVEY_RUN] Counts [{total_counts}] hit ceiling [{self.max_counts_limit}]. Resetting on-board buffer (no DPP resend)...")
                    
                    try: self.daq_device.data_acquisition_stop()
                    except: pass
                    
                    self.daq_device.clear_spectrum()
                    self.daq_device.timers_reset()
                    self.daq_device.data_acquisition_start()
                    
                    baseline_spectrum = []
                    self.survey_elapsed_seconds = 0
                    self.survey_hardware_live_time_ms = 0.0
                    self.current_isotope_id = "Buffer Reset. Re-accumulating..."
                    continue
                
                if total_counts >= self.min_counts_trigger:
                    self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum, self.survey_elapsed_seconds)
                else:
                    self.current_isotope_id = f"Accumulating ({total_counts}/{self.min_counts_trigger} cts)"
                    
        except Exception as e:
            logger.error(f"[HARDWARE] Continuous survey thread encountered an exception: {e}", exc_info=True)
            self.status_text = f"Survey Error: {e}"; self.state = 'IDLE'
        finally:
            # Runs on every exit path - normal loop exit, an error above, OR task
            # cancellation (stop_execution() calls _main_loop_task.cancel(), which
            # throws CancelledError into whatever await this coroutine is suspended
            # on - almost always asyncio.sleep(1.0) mid-poll. CancelledError is a
            # BaseException, so it skips the `except Exception` above entirely and
            # previously skipped this stop call too, since it used to live right
            # after the while loop instead of here. Without it, STOP left the
            # hardware physically running: it kept accumulating real counts (later
            # silently wiped by the next START's forced BRAM-clear) AND kept
            # incrementing Timer C the whole time acquisition sat "stopped" - which
            # is exactly what inflated the elapsed time relative to true counts.
            try: self.daq_device.data_acquisition_stop()
            except: pass
            try: self.daq_device.close()
            except: pass
            logger.info("[SURVEY_RUN] Shared master loop context released safely.")


    def _execute_ml_pipeline(self, raw_spectrum: list[int], live_time : int) -> str:
        """Executes ML pipeline on live spectrum data."""
        return self.ml_inference.inference_pipeline(spectrum_data=raw_spectrum, spectrum_live_time=live_time)


    def start_batch_recording(self, target_time: int, total_runs: int, prefix: str):
        """Assembles automated structural script loops mapping data files."""
        logger.warning(f"[DAQ_ACTION] Operator triggered automated multi-run batch recording -> runs={total_runs}")
        if self.state != 'IDLE': return
        self.batch_target_time = target_time; self.batch_total_runs = total_runs; self.batch_prefix = prefix
        self.state = 'BATCH_RECORDING'
        self._main_loop_task = asyncio.create_task(self._batch_recording_worker_loop())

    async def _batch_recording_worker_loop(self):
        """Automated file system serialization thread worker array loop."""
        # Every run in this batch shares the same target duration, so the hardware
        # Preset register only needs to be set once here - not per run. This gives
        # the board's own clock millisecond-precision control over when Timer C
        # (live time) stops, rather than relying purely on the ~1s software poll
        # below to detect "elapsed >= target" after the fact.
        preset_ok = self._set_timers_preset(self.batch_target_time * 1000)
        if not preset_ok:
            logger.warning("[BATCH_WORKER] Hardware timer preset could not be set - falling back to software-only timing (expect some overshoot past the target duration).")
        
        for run_idx in range(self.batch_total_runs):
            if self.state != 'BATCH_RECORDING': break
            self.batch_current_run = run_idx + 1
            logger.info(f"[BATCH_WORKER] Arranging sequence trace run [{self.batch_current_run}/{self.batch_total_runs}]...")
            self.batch_status_text = f"Configuring run {self.batch_current_run} of {self.batch_total_runs}..."
            self.batch_elapsed_seconds = 0
            
            # Reuses the already-programmed device handle (see push_active_profile_to_board) -
            # no DPP parameters are resent here for each run in the batch.
            if self.daq_device is None:
                logger.error("[BATCH_WORKER] No programmed device handle available. Was the board ever probed/calibrated?")
                self.batch_status_text = "Hardware error: Board not programmed"; break
            
            try:
                self.daq_device.open(); self.daq_device.clear_spectrum(); self.daq_device.timers_reset(); self.daq_device.data_acquisition_start()
            except Exception as e:
                logger.error(f"[BATCH_WORKER] Hardware access dropped during sequence initiation step: {e}", exc_info=True)
                self.batch_status_text = f"Hardware error: {e}"; break
                
            try:
                while self.batch_elapsed_seconds < self.batch_target_time and self.state == 'BATCH_RECORDING':
                    await asyncio.sleep(1.0)
                    if not self.verify_runtime_hardware_safety(): break
                    self.batch_elapsed_seconds = int(self.daq_device.timers_read()["tmr_c"] / 1000)
                    self.batch_spectrum = self.daq_device.read_spectrum()
                    self.batch_status_text = f"Run [{self.batch_current_run}/{self.batch_total_runs}] -> Live-Time: {self.batch_elapsed_seconds}/{self.batch_target_time}s"
                    
                if self.state != 'BATCH_RECORDING':
                    return
                
                # Stop acquisition immediately so the on-board timers/spectrum freeze at
                # this exact moment. Without this, acquisition keeps running physically
                # while we perform the final reads below, so the reported live/real time
                # drifts well past the requested target the longer those reads take.
                try:
                    self.daq_device.data_acquisition_stop()
                except Exception as e:
                    logger.error(f"[BATCH_WORKER] Failed to stop acquisition cleanly before final read: {e}", exc_info=True)
                
                final_spectrum = self.daq_device.read_spectrum()
                
                # Final timer read for the most accurate final live/real time values
                # (used by both the .json and .spe metadata below). Safe to do now since
                # acquisition is already stopped and the registers are no longer moving.
                try:
                    final_timers = self.daq_device.timers_read()
                except Exception:
                    final_timers = {}
                
                final_live_ms = float(final_timers.get("tmr_c", self.batch_elapsed_seconds * 1000) or self.batch_elapsed_seconds * 1000)
                final_real_ms = float(final_timers.get("tmr_a", final_live_ms) or final_live_ms)
                final_live_s = final_live_ms / 1000.0
                final_real_s = final_real_ms / 1000.0
                
                time_now = datetime.now()
                os.makedirs(self.OUTPUT_FOLDER, exist_ok=True)
                file_stamp = time_now.strftime("%Y%m%d_%H%M%S")
                base_filepath = os.path.join(self.OUTPUT_FOLDER, f"{file_stamp}_{self.system.serial_number}_{self.batch_prefix}_run{run_idx:04d}")
                spectrum_id = f"RUN_{run_idx}"
                
                # Single source of truth for both file formats below (issue #42: the
                # .spe file was carrying less metadata than the .json - sources,
                # attenuators, and detector info were missing from it).
                metadata = self._build_spectrum_metadata(
                    num_channels=len(final_spectrum), run_idx=run_idx, live_time_s=final_live_s
                )
                
                logger.info(f"[BATCH_WORKER] Committing spectrum array json to root: {base_filepath}.json")
                with open(f"{base_filepath}.json", "w", encoding="utf-8") as jf:
                    json.dump({"id": spectrum_id, "metadata": metadata, "data": final_spectrum}, jf, indent=2)
                
                logger.info(f"[BATCH_WORKER] Committing spectrum array spe to root: {base_filepath}.spe")
                self._write_spe_file(
                    filepath_base=base_filepath, spectrum_id=spectrum_id, spectrum=final_spectrum,
                    metadata=metadata, live_time_s=final_live_s, real_time_s=final_real_s, time_now=time_now
                )
            finally:
                # Always stop acquisition (harmless/idempotent if the explicit stop
                # above already ran) and close this run's connection, no matter how
                # the block above exited: normal completion, an aborted run (state
                # changed externally), or task cancellation via STOP - which throws
                # CancelledError straight through the awaited sleep, bypassing
                # everything else in this block including the explicit stop above.
                # Without this, a cancelled batch run left the hardware physically
                # running (and the serial connection open) indefinitely.
                try: self.daq_device.data_acquisition_stop()
                except: pass
                try: self.daq_device.close()
                except: pass
                
        self.state = 'IDLE'; self.batch_status_text = "Batch measurements finished successfully."

    def _build_spectrum_metadata(self, num_channels: int, run_idx: int, live_time_s: float) -> dict:
        """Assembles the full metadata block attached to a recorded spectrum. This is
        the single source of truth reused by both the .json and .spe writers, so the
        two file formats always carry identical information (issue #42: previously
        the .spe file's $SPE_REM section only had a handful of fields while the
        .json had richer metadata like sources/attenuators/detector info)."""
        prof = self.system.hw_profile
        rt = self.system.runtime_metadata
        vga_gain = float(prof.get("vga_gain_coarse", 6.0) or 6.0)
        return {
            "Material type": rt.get("Material type", "Source"),
            "Material form": rt.get("Material form", "point"),
            "Sources": rt.get("Sources", []),
            "Attenuators": rt.get("Attenuators", []),
            "Detector type": prof.get("Detector type", "UNKNOWN"),
            "Detector geometry": prof.get("Detector geometry", "UNKNOWN"),
            "Detector size": prof.get("Detector size", "UNKNOWN"),
            "Detector type number": prof.get("Detector type number", "UNKNOWN"),
            "Detector serial number": prof.get("Detector serial number", "UNKNOWN"),
            "Analyzer name": prof.get("Analyzer name", "UNKNOWN"),
            "Analyzer serial number": self.system.serial_number,
            "Analyzer gain (keV/ch)": vga_gain,
            "Number of channels": num_channels,
            "Energy calibration offset (keV)": prof.get("calib_a0", 0.0),
            "Energy calibration linear (keV/ch)": prof.get("calib_a1", 1.0),
            "Energy calibration quadratic (keV/ch2)": prof.get("calib_a2", 0.0),
            "Spectrum acquisition date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Spectrum live time (s)": live_time_s,
            "Sequence run index": run_idx,
        }

    def _write_spe_file(self, filepath_base: str, spectrum_id: str, spectrum: list,
                         metadata: dict, live_time_s: float, real_time_s: float, time_now: datetime) -> None:
        """Writes an ASCII IEC/ANSI-style .spe file whose $SPE_REM block mirrors the
        SAME metadata dict written to the companion .json file (see
        _build_spectrum_metadata), so the two formats never drift out of sync again.
        Structure modeled after the separate reference utility's .spe writer."""
        prof = self.system.hw_profile
        num_channels = len(spectrum)
        with open(f"{filepath_base}.spe", "w", encoding="ascii") as sf:
            sf.write(f"$SPEC_ID:\n{spectrum_id}\n")
            sf.write(f"$DATE_MEA:\n{time_now.strftime('%m/%d/%Y %H:%M:%S')}\n")
            sf.write(f"$MEAS_TIM:\n{live_time_s:.2f} {real_time_s:.2f}\n")
            sf.write("$SPE_REM:\n")
            sf.write(f"Material Type: {metadata['Material type']}\n")
            sf.write(f"Material Form: {metadata['Material form']}\n")
            if metadata['Sources']:
                for i, src in enumerate(metadata['Sources']):
                    fields = ", ".join(f"{k}={v}" for k, v in src.items())
                    sf.write(f"Source[{i}]: {fields}\n")
            else:
                sf.write("Sources: none\n")
            if metadata['Attenuators']:
                for i, att in enumerate(metadata['Attenuators']):
                    fields = ", ".join(f"{k}={v}" for k, v in att.items())
                    sf.write(f"Attenuator[{i}]: {fields}\n")
            else:
                sf.write("Attenuators: none\n")
            sf.write(f"Detector Type: {metadata['Detector type']}\n")
            sf.write(f"Detector Geometry: {metadata['Detector geometry']}\n")
            sf.write(f"Detector Size: {metadata['Detector size']}\n")
            sf.write(f"Detector Type Number: {metadata['Detector type number']}\n")
            sf.write(f"Detector Serial Number: {metadata['Detector serial number']}\n")
            sf.write(f"Analyzer Name: {metadata['Analyzer name']}\n")
            sf.write(f"Analyzer Serial Number: {metadata['Analyzer serial number']}\n")
            sf.write(f"Analyzer Gain (keV/ch): {metadata['Analyzer gain (keV/ch)']:.4f}\n")
            sf.write(f"Number of Channels: {metadata['Number of channels']}\n")
            sf.write(f"Sequence Run Index: {metadata['Sequence run index']:04d}\n")
            sf.write("$MCA_CAL:\n3\n")
            sf.write(f"{prof.get('calib_a0', 0.0):.7e} {prof.get('calib_a1', 1.0):.7e} {prof.get('calib_a2', 0.0):.7e}\n")
            sf.write(f"$DATA:\n0 {num_channels - 1}\n")
            for counts in spectrum:
                sf.write(f"{int(counts)}\n")
            sf.write("$ENDRECORD:\n")

    def stop_execution(self):
        """Halts the active acquisition loop without discarding the collected spectrum.
        The last spectrum trace and identification result are left exactly as they were
        so the operator can still review what was captured before pressing STOP."""
        logger.warning(f"[SERVICE] Operator pressed STOP button. Halting acquisition out of state: {self.state}")
        was_survey = self.state == 'ACQUIRING_SURVEY'
        
        self.state = 'IDLE'
        self.batch_status_text = "Halted by Operator"
        
        if was_survey:
            # Freeze the plot/ID at their last values instead of resetting to Standby.
            self.survey_stopped_with_data = bool(self.live_spectrum)
            self.status_text = "Survey Stopped - Showing Last Spectrum"
        else:
            self.status_text = "Halted by Operator"
            self.current_isotope_id = "Standby"
        
        if self._main_loop_task: self._main_loop_task.cancel()

    def clear_survey_data(self):
        """Explicitly wipes the accumulated survey spectrum trace (and its associated
        timers/state) on operator demand. This is the ONLY path that resets the live
        spectrum now - starting a new survey run no longer does this automatically.
        Works both while idle and while a survey is actively accumulating: in the
        latter case the running acquisition loop performs the hardware-level reset
        on its next tick and keeps surveying, so STOP is not required first.
        The background spectrum profile is intentionally left untouched."""
        if self.state not in ('IDLE', 'ACQUIRING_SURVEY'):
            logger.warning(f"[SERVICE] CLEAR request rejected. Core state is busy: {self.state}")
            return
        
        logger.warning("[SERVICE] Operator pressed CLEAR button. Wiping accumulated survey spectrum (background profile preserved).")
        
        if self.state == 'ACQUIRING_SURVEY':
            # Let the active acquisition loop perform the actual hardware-level clear
            # on its own next tick rather than tearing down and rebuilding the survey.
            self.clear_requested = True
        else:
            # No survey is running, so the acquisition loop won't pick up a flag - the
            # on-board accumulator has to be cleared directly here instead. This reuses
            # the existing programmed handle; it does NOT resend any DPP parameters.
            if self.daq_device is not None and self.is_hardware_available:
                try:
                    self.daq_device.open()
                    self.daq_device.clear_spectrum()
                    self.daq_device.timers_reset()
                    self.daq_device.close()
                except Exception as e:
                    logger.error(f"[SERVICE] Hardware-level CLEAR failed: {e}", exc_info=True)
            
            self.live_spectrum = []
            self.survey_elapsed_seconds = 0
            self.survey_hardware_live_time_ms = 0.0
            self.survey_stopped_with_data = False
            self.current_isotope_id = "Standby"
            self.status_text = "Spectrum Cleared - Ready"

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