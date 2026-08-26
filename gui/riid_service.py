"""Backend service layer for the RIID station.

Owns the DAQ hardware handle, the background/continuous-survey/batch
acquisition loops, the ML inference pipeline invocation, and spectrum file
I/O (SPE/JSON read-write, zip bundling, delete). The view modules
(``view_spectrum_id.py``, ``view_recording.py``, ``view_download.py``,
``view_calibration.py``) all drive the UI by calling into a single shared
:class:`RIIDCoreService` instance rather than touching the hardware or disk
directly.
"""

import os
import json
import io
import zipfile
import tempfile
import asyncio
import threading
from collections import deque
from datetime import datetime, timezone
from config import logger, SPECTRA_BATCH_DIR, SPECTRA_BACKGROUND_DIR, SPECTRA_RIID_DIR
from core.daq_commands import DaqCommands
from state_engine import SpectrumAcquisitionSystem
from ml_inference import MlInference
from ml_preprocessing import MLPreprocessing
from mcu_interface import ArduinoInterface
from wifi_interface import WifiInterface

class RIIDCoreService:
    """Central hardware/service orchestration hub for the RIID station.

    Manages the lifecycle of the DAQ device handle, runs the background,
    continuous-survey, and batch-recording acquisition loops as asyncio
    tasks, invokes the ML classification pipeline on each survey tick, and
    handles all spectrum file I/O (SPE/JSON persistence, zip bundling for
    download, deletion). A single instance is constructed in ``main.py`` and
    shared by every view module for the lifetime of the app.
    """

    # Centralized folder destination constant.
    OUTPUT_FOLDER = SPECTRA_BATCH_DIR

    # Maps each bulk-download category to its data/spectra/ subfolder.
    SPECTRA_CATEGORY_DIRS = {
        'background': SPECTRA_BACKGROUND_DIR,
        'batch': SPECTRA_BATCH_DIR,
        'riid': SPECTRA_RIID_DIR,
    }

    # Programmatic class constant for the unsigned 32-bit hardware register gating limit (2^32 - 1)
    MAX_32BIT_UINT = int(2**32 - 1)

    # Default operational parameters - single source of truth. Referenced both
    # here (initial state) and by the view layer's widget-creation/fallback-
    # parsing code, instead of each place re-typing its own copy of the same
    # number (which had already drifted out of sync in a couple of spots).
    DEFAULT_MAX_COUNTS_LIMIT = 15000
    DEFAULT_BG_TARGET_TIME_S = 300
    DEFAULT_BATCH_TARGET_TIME_S = 300
    DEFAULT_BATCH_TOTAL_RUNS = 1
    DEFAULT_BATCH_PREFIX = "spectrum_run"
    # Minimum single-channel count (after background subtraction) required
    # before MlInference.inference_pipeline() attempts classification at all -
    # was hardcoded separately at both construction sites (__init__ and
    # set_ml_model), now a single source of truth referenced by both.
    DEFAULT_ML_MIN_COUNTS = 10

    # Dynamic hysteresis (auto-reset) model, replacing
    # the old static total-count threshold. That static value caused two
    # opposite problems reported in practice: a high-activity source (e.g.
    # Eu-152) could hit it in ~1s, forcing a reset every 1-3s - too fast to
    # read a result or accumulate meaningful statistics - while a low-activity
    # source (e.g. a weak Cs-137) could take several minutes to reach the
    # same static count, far past any reasonable identification latency.
    #
    # Uses the PEAK SINGLE CHANNEL count of the background-subtracted
    # spectrum - the exact same metric MlInference.inference_pipeline() itself
    # checks against min_counts before attempting classification at all - not
    # the total/integral spectrum count. This keeps the auto-reset directly
    # aligned with when the ML pipeline can actually produce a real result,
    # rather than a proxy (total counts) that only loosely correlates with it.
    #
    # Model: threshold(peak_ch_rate) = clamp(FLOOR, avg_peak_ch_rate *
    # TARGET_TIME_S, CEILING), where avg_peak_ch_rate is a SLIDING WINDOW
    # average of the peak channel's recent instantaneous rate (the last
    # HYSTERESIS_WINDOW_SAMPLES samples, ~1 per second) - not a cumulative
    # average since the last reset. A cumulative average gets progressively
    # more sluggish to react the longer a session runs, since old samples
    # increasingly dominate it; a sliding window stays equally responsive to a
    # genuine rate change (e.g. a source being moved closer) no matter how
    # long the current cycle has been running.
    HYSTERESIS_TARGET_TIME_S = 25.0
    # Number of recent instantaneous peak-channel-rate samples (~1/s) averaged
    # for the sliding-window rate estimate.
    HYSTERESIS_WINDOW_SAMPLES = 5
    # Used only as a fallback multiplier for the brief window before the
    # first peak-channel-rate sample exists (see
    # _compute_dynamic_hysteresis_threshold). The main formula is additive
    # (min_counts + rate*TARGET_TIME_S), whose additive term alone already
    # guarantees the threshold sits comfortably above min_counts once a real
    # rate is known - so no multiplicative floor is needed once that's true.
    HYSTERESIS_FLOOR_MULTIPLIER = 1.6
    # A single channel reaching this is implausible even at very high total
    # count rates - a photopeak typically captures only a modest fraction of
    # total counts - so this is a generous safety cap, not something normal
    # operation should ever actually reach.
    HYSTERESIS_CEILING_COUNTS = 50_000
    
    # Adaptive ML trigger threshold (min_counts): the operator's configured
    # value (ML_MIN_COUNTS_TARGET default, via the slider) works well for
    # well-lit sources, but a faint source (e.g. ~25% above background) could
    # take 2+ minutes to reach it at all, since MlInference won't attempt
    # classification before then. Lowering min_counts globally would fix that
    # but degrade statistics (and raise false-positive risk) for every
    # source, including ones that don't need it.
    #
    # Model: effective_min_counts = clamp(ABSOLUTE_FLOOR, avg_peak_channel_rate
    # * TIME_BUDGET_S, operator_target). A source fast enough to reach the
    # operator's target within TIME_BUDGET_S uses the full target unchanged
    # (preserving today's good statistics for active sources); a slower
    # source gets a proportionally lower effective threshold instead, bounded
    # below by ABSOLUTE_FLOOR so it never drops so low the result becomes
    # statistically meaningless. Verified against the reported scenario: a
    # source at ~25% above background goes from >120s to ~60s to first
    # trigger a classification attempt; a source at typical high-activity
    # rates is unaffected (its target is already reached well within budget).
    ML_TRIGGER_ABSOLUTE_FLOOR = 5
    ML_TRIGGER_TIME_BUDGET_S = 60.0
    
    # Rolling window size for cps_history (the count-rate-over-time plot's
    # data) - ~4 minutes at the survey loop's 1s poll interval.
    CPS_HISTORY_LEN = 240

    def __init__(self, ml_model_name : str):
        """Builds the service in its idle, pre-hardware-probe state.

        Args:
            ml_model_name (str): Name of the ML model to load for RIID
                classification (see ``ml_inference.MlInference``). Models
                live under ``gui/ml_models/``.
        """
        logger.info("[SERVICE_INIT] Initializing spectroscopy operations hub...")
        self.system = SpectrumAcquisitionSystem()
        self.system.sync_hardware_profile()
        
        # Shared authoritative singleton hardware controller instance anchor
        self.daq_device = None
        # Guards every actual self.daq_device.* call (see _call_hw's
        # docstring for why this needs to be a real threading.Lock, not
        # asyncio.Lock).
        self._hw_lock = threading.Lock()

        # Microcontroller visualization interface: leveraging Arduino Uno Q's
        # RPC router. Must be constructed before the first set_state() call
        # below, since set_state() dereferences self.mcu_iface.
        self.mcu_iface = ArduinoInterface()

        # Client for the standalone WiFi mode daemon's local socket (see
        # wifi/wifi_mode_daemon.py) - used by view_network.py's Network Setup
        # card. Unrelated to mcu_iface/RPC bridge above past sharing the same
        # wire format; this never touches the DAQ/MCU hardware.
        self.wifi_iface = WifiInterface()

        # Operational State Flags
        self.set_state('IDLE')
        self.is_hardware_available = False
        # True while analyzing a loaded pre-recorded spectrum instead of live
        # DAQ data - coexists with state == 'IDLE' rather than being a new
        # state value, since it isn't a DAQ activity like the other three.
        # Cleared by clear_survey_data() (the RESTART button).
        self.offline_mode = False
        
        # Dynamic Spectrum Vector Storage Buffers
        self.live_spectrum = []
        self.background_spectrum = []  
        self.batch_spectrum = [] 
        
        # Trigger thresholds for automated identification pipelines
        self.max_counts_limit = self.DEFAULT_MAX_COUNTS_LIMIT
        # Enabled by default (dynamic peak-channel-based auto-reset).
        # When disabled, max_counts_limit above is used directly as a manually-
        # set threshold instead - still compared against the peak single
        # channel, never the integral spectrum count, in either mode.
        self.auto_hysteresis_enabled = True
        
        # Must be initialized here, not lazily by the view layer -
        # SpectrumPlotContainer, constructed before ControlPanelSidebar in
        # main.py, reads this directly for its own log-scale checkbox.
        self.use_log_scale = False
        
        # Configuration presets for structural automated multi-run recordings
        self.batch_target_time = self.DEFAULT_BATCH_TARGET_TIME_S
        self.batch_total_runs = self.DEFAULT_BATCH_TOTAL_RUNS
        self.batch_current_run = 0
        self.batch_elapsed_seconds = 0
        self.batch_prefix = self.DEFAULT_BATCH_PREFIX
        self.batch_status_text = "Ready to acquire file records."
        
        # Live display state fields
        self.elapsed_seconds = 0
        self.bg_target_time = self.DEFAULT_BG_TARGET_TIME_S
        self.bg_accumulated_seconds = 0
        self.survey_elapsed_seconds = 0
        self.bg_progress = 0.0
        # Hardware live/real time captured for the last background spectrum
        # (either recorded fresh via _bg_recording_sequence, or loaded from a
        # file via load_background_spectrum). Tracked as two independently
        # measured values, since real time can differ from live time
        # whenever there's dead time during the capture.
        self.bg_hardware_live_time_ms = 0.0
        self.bg_hardware_real_time_ms = 0.0
        # Same independent live/real-time tracking, for the continuous
        # survey / RIID spectrum.
        self.survey_hardware_live_time_ms = 0.0
        self.survey_hardware_real_time_ms = 0.0
        
        self.current_isotope_id = "Standby"
        self.status_text = "System Initialized"
        
        # The model name for the "Model"
        # metric card, and the FULL per-class probability breakdown from the
        # most recent successful inference (all classes, not just ones above
        # self.ml_inference.CLASSIFICATION_THRESHOLD) for the Class Probabilities
        # bar chart. None whenever there's no result yet, or the last attempt
        # returned a plain status string instead (e.g. "not enough counts").
        self.ml_model_name = ml_model_name
        self.last_ml_result = None
        # Tracks the isotope set from the last logged ML detection (as a
        # frozenset of names, or None) - lets _execute_ml_pipeline() log only
        # when the result actually CHANGES, instead of re-logging an identical
        # line every ~1s poll tick during a long survey.
        self._last_logged_detection = None
        
        # Rolling window of (elapsed_seconds, instantaneous_cps, source)
        # samples for the count-rate-over-time plot - distinct from the
        # existing cumulative-average CPS shown in the spectrum plot's legend.
        # source is 'survey' or 'bg', so the plot can color each segment to
        # match the spectrum plot's own trace colors (blue/gray respectively).
        self.cps_history = deque(maxlen=self.CPS_HISTORY_LEN)
        self._prev_survey_counts = 0
        self._prev_survey_elapsed_s = 0.0
        # Same delta-tracking, for background recording's own CPS samples.
        self._prev_bg_counts = 0
        self._prev_bg_elapsed_s = 0.0
        # The hardware live-time timer (survey_hardware_live_time_ms /
        # bg's own tmr_c read) resets to 0 on every hysteresis-cycle buffer
        # reset or new BG recording, but cps_history is intentionally
        # preserved across those events - so each sample's x-value is offset by
        # however much time was already "banked" from prior cycles, keeping the
        # x-axis monotonically increasing instead of jumping backward (which
        # Plotly would draw as a corrupted, overlapping line, since points are
        # connected in array order, not sorted by x). Reset only by
        # clear_cps_history() - the same explicit action that clears the history.
        self._cps_history_time_offset_s = 0.0
        
        # Sliding window of recent instantaneous peak-channel-rate
        # samples (background-subtracted spectrum), used by
        # _compute_dynamic_hysteresis_threshold() - deliberately NOT reset on
        # an automatic hysteresis-cycle reset (only by clear_cps_history(),
        # alongside cps_history above), so the rate estimate stays continuous
        # across reset boundaries instead of collapsing back to empty every
        # ~20s and forcing the threshold down to the floor until it refills.
        self._peak_channel_rate_history = deque(maxlen=self.HYSTERESIS_WINDOW_SAMPLES)
        self._prev_peak_channel_value = 0.0
        self._prev_peak_channel_elapsed_s = 0.0
        # Once the peak channel first reaches min_counts within a cycle (i.e.
        # the ML pipeline is actually triggered for the first time since the
        # last reset), min_counts stops being re-adapted for the rest of that
        # cycle - see the poll loop and ML_TRIGGER_ABSOLUTE_FLOOR's docstring.
        # Reset to False at the start of every fresh accumulation cycle
        # (survey start, hysteresis auto-reset, and explicit CLEAR/RESTART).
        self._ml_trigger_fired_this_cycle = False
        
        # Tracks whether the last survey was halted by the operator (STOP) while
        # holding valid spectrum data, so the plot can keep rendering it "frozen"
        # instead of disappearing once the state leaves RIID_SURVEY.
        self.survey_stopped_with_data = False
        
        # Set by clear_survey_data() while a survey is actively running; the
        # acquisition loop polls this flag and performs the actual hardware-level
        # reset on its own next tick, so CLEAR works without requiring STOP first.
        self.clear_requested = False
        
        # Asynchronous Task Tracking Handles
        self._main_loop_task = None
        self._heartbeat_task = None

        # ML inference model
        self.ml_inference = MlInference(ml_model_name = ml_model_name, min_counts = self.DEFAULT_ML_MIN_COUNTS)

    def _call_hw(self, func, *args, **kwargs):
        """Thread-safe wrapper around a single hardware call - always used as
        the target of asyncio.to_thread(self._call_hw, self.daq_device.X, ...)
        rather than calling self.daq_device.X directly.
        
        Exists specifically because asyncio task cancellation (e.g. the
        operator pressing STOP mid-poll, which cancels the running loop's
        task) cannot forcibly stop a worker thread that's already executing
        inside a prior asyncio.to_thread() call - Python has no mechanism to
        kill a running thread from outside. The orphaned thread keeps running
        the original call to completion, even after the cancelled coroutine
        has already moved on to its own finally block and wants to issue a
        NEW hardware call (e.g. data_acquisition_stop() during cleanup). That
        means two threads could end up touching the same serial port object
        at the same time, which pyserial does not support safely.
        
        An asyncio.Lock would NOT fix this - it only serializes coroutines
        that are awaiting it at the asyncio level, and has no power over an
        OS thread that's already running independently of the event loop. A
        real threading.Lock, acquired here INSIDE the worker thread itself,
        enforces true mutual exclusion regardless of any asyncio-level
        cancellation timing: the second call simply blocks (on the thread
        pool's own worker thread, not the event loop) until the first one
        actually finishes.
        """
        with self._hw_lock:
            return func(*args, **kwargs)

    def set_state(self, state_string : str) -> None:
        self.state = state_string

        # Check whether the Arduino RPC bridge connection is valid before sending any update request
        if self.mcu_iface.get_status():
            # Valid status strings: "IDLE", "BG_RECORDING", "RIID_SURVEY", "BATCH_RECORDING"
            self.mcu_iface.update_status(self.mcu_iface.lookup_state_idx(state_string))
            self.mcu_iface.update_text(state_string)

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
                self._call_hw(self.daq_device.close)
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
            self._call_hw(self.daq_device.open)
            # A freshly-programmed board implies a freshly-cleared accumulator; keep the
            # on-chip registers and the software-side survey bookkeeping in sync.
            self._call_hw(self.daq_device.clear_spectrum)
            self._call_hw(self.daq_device.timers_reset)
            self._call_hw(self.daq_device.close)
            
            self.live_spectrum = []
            self.survey_elapsed_seconds = 0
            self.survey_hardware_live_time_ms = 0.0
            self.survey_hardware_real_time_ms = 0.0
            self.survey_stopped_with_data = False
            return True
        except Exception as e:
            logger.error(f"[MCA_PROG] Master parameter injection failed: {e}", exc_info=True)
            return False

    def _set_timers_preset(self, preset_ms: int) -> bool:
        """Updates ONLY the Preset register (Timer C collection window) on the
        ALREADY-programmed board handle, so a survey/background/batch run can
        configure its exact millisecond collection window on the hardware's
        own clock - without resending any other DPP parameter group (shaper,
        gain, BLR, etc.), which stays reserved for push_active_profile_to_board()
        only (hardware probe / an explicit calibration commit).
        
        Delegates straight to DaqCommands.set_timers_preset(), so this code
        never needs to reach into the HAL directly (constructing Dpp_Timers
        or importing DppSubmodules) - the Python API owns that
        read-modify-write against the Timers DPP submodule (group 4)
        internally.
        
        Returns True on success, False if there's no programmed handle or the
        transmission failed (callers should fall back to pure software timing)."""
        if self.daq_device is None:
            logger.warning("[SERVICE] Cannot set timer preset - no programmed device handle available.")
            return False
        try:
            success = self.daq_device.set_timers_preset(preset_ms)
            if success:
                logger.info(f"[SERVICE] Timer preset updated to {preset_ms} ms (Timers submodule only, no other DPP groups resent).")
            else:
                logger.warning(f"[SERVICE] Timer preset update to {preset_ms} ms was not acknowledged by the board.")
            return success
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
                    if DaqCommands.is_device_present():
                        self.is_hardware_available = True
                        if "Disconnected" in self.status_text:
                            self.status_text = "Hardware Connected & Ready"
                    else:
                        logger.error("[HEARTBEAT] Physical device disconnected - autodiscovery no longer finds a matching DAQ board.")
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

        # Starting a new background recording is always a hard break in the
        # count-rate plot's timeline, never a continuation - whatever ran
        # before (a survey the operator merely STOPped without CLEARing, a
        # batch job, a prior background) is unconditionally wiped rather than
        # bridged across via the x-axis time-offset, which only bridges
        # cleanly when every intervening activity remembers to bank its own
        # contribution into it. The hardware live-time timer gets the same
        # fresh start via _bg_recording_sequence()'s own timers_reset() call,
        # right after this, before acquisition begins.
        self.clear_cps_history()

        self.set_state('BG_RECORDING')
        self.current_isotope_id = "Recording Background..."
        self._main_loop_task = asyncio.create_task(self._bg_recording_sequence())

    async def _bg_recording_sequence(self):
        """Asynchronous worker for collecting background spectrum matrix arrays with accurate hardware live-time capture.
        Reuses the already-programmed device handle (see push_active_profile_to_board) -
        no DPP parameters are resent here. The on-board register clear below is specific
        to starting a fresh background capture and is unrelated to DPP programming.
        
        Every self.daq_device.* call below is offloaded via asyncio.to_thread() -
        these are synchronous serial I/O calls (each can take up to the port's
        own ~0.8s timeout), and without offloading them they'd block the
        entire asyncio event loop for their full duration on every single poll
        tick - including the UI's own 1-second tick timer, which is what was
        actually causing GUI updates to visibly lag behind their intended 1s
        cadence during any active DAQ operation."""
        logger.info("[BACKGROUND_RUN] Async recording pipeline worker mounting...")
        if self.daq_device is None:
            logger.error("[BACKGROUND_RUN] No programmed device handle available. Was the board ever probed/calibrated?")
            self.status_text = "BG Error: Board not programmed"; self.set_state('IDLE')
            return
        
        # Give the board's own clock millisecond-precision control over when Timer C
        # (live time) stops, matching this run's requested duration. Falls back to
        # pure software timing (with some overshoot) if this can't be set.
        if not self._set_timers_preset(self.bg_target_time * 1000):
            logger.warning("[BACKGROUND_RUN] Hardware timer preset could not be set - falling back to software-only timing.")
        
        # Defined before the try block (not alongside the other BG state resets
        # below) so it's always bound even if open()/clear_spectrum()/etc. raise
        # before the polling loop starts - finally references it unconditionally.
        bg_live_time_s = 0.0
        
        try:
            await asyncio.to_thread(self._call_hw, self.daq_device.open)
            await asyncio.to_thread(self._call_hw, self.daq_device.clear_spectrum)
            await asyncio.to_thread(self._call_hw, self.daq_device.timers_reset)
            await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_start)
            
            self.elapsed_seconds = 0
            self.bg_progress = 0.0
            self._prev_bg_counts = 0
            self._prev_bg_elapsed_s = 0.0
            
            while self.elapsed_seconds < self.bg_target_time and self.state == 'BG_RECORDING':
                await asyncio.sleep(1.0)
                if not self.verify_runtime_hardware_safety():
                    break
                    
                # Read hardware timers dynamically
                hw_timers = await asyncio.to_thread(self._call_hw, self.daq_device.timers_read)
                self.elapsed_seconds = int(hw_timers.get("tmr_c", 0) / 1000)
                self.live_spectrum = await asyncio.to_thread(self._call_hw, self.daq_device.read_spectrum)
                self.bg_progress = min(float(self.elapsed_seconds / self.bg_target_time), 1.0) if self.bg_target_time > 0 else 1.0
                self.status_text = f"Recording BG: {self.elapsed_seconds}/{self.bg_target_time}s"
                
                # Same instantaneous count-rate sampling as the survey loop, so the
                # count-rate plot also shows activity during background recording -
                # tagged 'bg' so the plot can color it gray, matching the spectrum
                # plot's own Background trace color.
                bg_live_time_s = float(hw_timers.get("tmr_c", 0)) / 1000.0
                bg_total_counts = sum(self.live_spectrum) if self.live_spectrum else 0
                bg_delta_counts = bg_total_counts - self._prev_bg_counts
                bg_delta_time_s = bg_live_time_s - self._prev_bg_elapsed_s
                if bg_delta_time_s > 0:
                    bg_instantaneous_cps = max(bg_delta_counts, 0) / bg_delta_time_s
                    self.cps_history.append((self._cps_history_time_offset_s + bg_live_time_s, bg_instantaneous_cps, 'bg'))
                self._prev_bg_counts = bg_total_counts
                self._prev_bg_elapsed_s = bg_live_time_s
                
            if self.state == 'BG_RECORDING':
                self.background_spectrum = await asyncio.to_thread(self._call_hw, self.daq_device.read_spectrum)
                
                # Extract final absolute background hardware live-time directly from the MCA registers
                final_bg_timers = await asyncio.to_thread(self._call_hw, self.daq_device.timers_read)
                self.bg_hardware_live_time_ms = float(final_bg_timers.get("tmr_c", self.bg_target_time * 1000))
                # tmr_a (real time, per the timers_a_live_time=False config set
                # at DPP programming time) is read separately from live time -
                # equating the two would only be coincidentally correct at
                # zero dead time.
                self.bg_hardware_real_time_ms = float(final_bg_timers.get("tmr_a", self.bg_hardware_live_time_ms) or self.bg_hardware_live_time_ms)
                self.bg_accumulated_seconds = int(self.bg_hardware_live_time_ms / 1000)
                
                self.bg_progress = 1.0
                self.status_text = "Background Spectrum Ready"
                self.current_isotope_id = "BG Complete. Ready for Survey."
                self.set_state('IDLE')

                # Update ML model background
                self.ml_inference.update_bkgnd_data(new_bkgnd_data=self.background_spectrum, new_bkgnd_live_time=self.bg_accumulated_seconds)

                logger.info(f"[BACKGROUND_RUN] Background spectrum saved. Pure HW Live-Time: {self.bg_hardware_live_time_ms} ms")
        except Exception as e:
            logger.error(f"[BACKGROUND_RUN] Pipeline error: {e}", exc_info=True)
            self.status_text = f"BG Error: {e}"; self.set_state('IDLE'); self.bg_progress = 0.0
        finally:
            # Runs on every exit path - normal completion, an error above, or an
            # aborted run (STOP pressed mid-BG, hardware lost, task cancelled).
            # Without this, the hardware keeps silently accumulating counts (and
            # Timer C keeps ticking) after a BG run ends, and self.live_spectrum -
            # only ever meant as a live-display side-channel during THIS BG run -
            # would be left behind for the next survey START to mistake for a
            # prior survey accumulation to resume (the actual cause of the survey's
            # first frame showing the just-recorded background spectrum).
            
            # Bank this BG session's elapsed time into the count-rate offset (same
            # mechanism as the hysteresis-cycle reset) - whatever comes next
            # (another BG recording or a live survey) continues the count-rate
            # plot's x-axis from here instead of restarting at 0 and corrupting
            # the line (see clear_cps_history's docstring for why that matters).
            self._cps_history_time_offset_s += bg_live_time_s
            self._prev_bg_counts = 0
            self._prev_bg_elapsed_s = 0.0
            
            try:
                await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_stop)
                await asyncio.to_thread(self._call_hw, self.daq_device.clear_spectrum)
                await asyncio.to_thread(self._call_hw, self.daq_device.timers_reset)
            except Exception as e:
                logger.error(f"[BACKGROUND_RUN] Failed to cleanly halt/clear hardware after BG capture: {e}", exc_info=True)
            self.live_spectrum = []
            try: await asyncio.to_thread(self._call_hw, self.daq_device.close)
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
        software by carrying the previously accumulated spectrum forward and adding
        each new hardware reading on top of it. The live-time timer is NOT
        reset by $AQ 1 (only an explicit $AQ 4 / timers_reset() does that, which ordinary
        START never calls), so it already persists correctly without any extra bookkeeping."""
        logger.info("[SERVICE] Operator initiated continuous radioisotope identification survey loop...")
        if self.state != 'IDLE': return
        
        self.survey_stopped_with_data = False
        self.set_state('RIID_SURVEY')
        self.current_isotope_id = "Resuming Accumulation..." if self.live_spectrum else "Accumulating Counts..."
        self._main_loop_task = asyncio.create_task(self._continuous_survey_sequence())

    async def _continuous_survey_sequence(self):
        """Asynchronous execution task interacting safely through open-ended constructor parameters initialization with exact HW timers.
        Reuses the already-programmed device handle (see push_active_profile_to_board) -
        no DPP parameters are resent here.
        
        IMPORTANT (per DPP4SiPM firmware docs, $AQ command): calling data_acquisition_start()
        (flag 0 or 1) "Cleans BRAM contents prior to starting" as an unconditional hardware
        side effect - this happens regardless of DPP reprogramming, and there is no flag to
        resume without clearing. So the previously accumulated spectrum is captured here
        BEFORE starting, and added back on top of every subsequent hardware
        reading, giving true continuity across STOP -> START despite the BRAM wipe.
        The on-board live-time timer (tmr_c) is untouched by $AQ 1 (only $AQ 4 /
        timers_reset() clears it, which an ordinary start never calls), so it already
        reads the correct cumulative value with no extra math needed.
        
        Every self.daq_device.* call below is offloaded via
        asyncio.to_thread() - these are synchronous serial I/O calls (each
        can take up to the port's own ~0.8s timeout), and without offloading
        them they'd block the entire asyncio event loop for their full
        duration on every poll tick - including the UI's own 1-second tick
        timer, which is what was actually causing GUI updates to visibly lag
        behind their intended 1s cadence during an active survey.
        _execute_ml_pipeline() below is deliberately NOT offloaded to a
        thread - TFLite inference on this model is fast enough that it isn't
        a meaningful contributor, and some ML runtimes have thread-affinity
        expectations that make blindly offloading them a risk not worth
        taking for a marginal gain."""
        logger.info("[SURVEY_RUN] Shared master API channel activated for live collection.")
        if self.daq_device is None:
            logger.error("[SURVEY_RUN] No programmed device handle available. Was the board ever probed/calibrated?")
            self.status_text = "Survey Error: Board not programmed"; self.set_state('IDLE')
            return
        try:
            await asyncio.to_thread(self._call_hw, self.daq_device.open)
            
            # Force the hardware Preset register back to "unlimited" before every
            # survey start (fresh AND resume alike). A prior BG recording or batch
            # run leaves the board's Preset at ITS target duration (see
            # _set_timers_preset); if left unchanged, the survey would silently
            # auto-stall the instant Timer C reaches that leftover value, well
            # before the operator intends to stop. This only touches the Timers
            # DPP submodule (group 4) - it does not clear BRAM/spectrum, so it's
            # safe to call unconditionally without disturbing the resumed accumulation.
            if not self._set_timers_preset(self.MAX_32BIT_UINT):
                logger.warning("[SURVEY_RUN] Could not reset timer preset to unlimited - survey may stall early if a prior BG/batch preset is still active on the board.")
            
            # Snapshot whatever was accumulated before this start - $AQ is about to wipe
            # the physical BRAM out from under us regardless of what we do here.
            previous_spectrum = list(self.live_spectrum) if self.live_spectrum else []
            
            if not previous_spectrum:
                # Genuinely fresh start (nothing to resume) - explicitly zero
                # the hardware live-time timer here. Without this, the FIRST
                # survey start in a fresh app session could silently inherit
                # whatever value Timer C already happened to be at (e.g. left
                # running from before this app even connected to the board),
                # showing a nonzero LIVE TIME immediately after pressing
                # START. The "timer persists across STOP -> START" design
                # documented above is correct for an actual resume - it just
                # assumes a known-zero baseline was established at least
                # once first, which this establishes.
                await asyncio.to_thread(self._call_hw, self.daq_device.timers_reset)
            
            await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_start)
            
            if previous_spectrum:
                logger.info(f"[SURVEY_RUN] Resuming on top of {sum(previous_spectrum)} previously accumulated counts (BRAM cleared by $AQ; live-time timer persists in hardware).")
            else:
                logger.info("[SURVEY_RUN] Resumed acquisition on existing programmed handle (no DPP resend).")
            
            # Re-sync the count-rate delta tracker to the ACTUAL state right now,
            # rather than trusting whatever _prev_survey_counts/_prev_survey_elapsed_s
            # were left at from before this start. This makes the first post-resume
            # count-rate sample correct regardless of whether the hardware live-time
            # timer actually persisted across the stop (the documented, expected
            # behavior) or not - either way, the delta on the next poll is computed
            # against a reference taken at THIS exact moment, so it can't come out
            # as a stale/spurious spike or a corrupted jump on the count-rate plot.
            try:
                resync_timers = await asyncio.to_thread(self._call_hw, self.daq_device.timers_read)
                self._prev_survey_elapsed_s = float(resync_timers.get("tmr_c", 0)) / 1000.0
            except Exception as e:
                logger.warning(f"[SURVEY_RUN] Could not re-sync count-rate timer reference on resume: {e}")
                self._prev_survey_elapsed_s = 0.0
            self._prev_survey_counts = sum(previous_spectrum) if previous_spectrum else 0
            
            while self.state == 'RIID_SURVEY':
                await asyncio.sleep(1.0)
                if not self.verify_runtime_hardware_safety():
                    break
                
                if self.clear_requested:
                    logger.warning("[SURVEY_RUN] CLEAR requested mid-survey. Resetting on-board accumulation registers without stopping the survey or resending DPP parameters...")
                    self.clear_requested = False
                    previous_spectrum = []
                    try: await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_stop)
                    except: pass
                    await asyncio.to_thread(self._call_hw, self.daq_device.clear_spectrum)
                    await asyncio.to_thread(self._call_hw, self.daq_device.timers_reset)
                    await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_start)
                    self.survey_elapsed_seconds = 0
                    self.survey_hardware_live_time_ms = 0.0
                    self.survey_hardware_real_time_ms = 0.0
                    self.live_spectrum = []
                    # Pressing CLEAR is an explicit "start fresh" action, so it
                    # DOES reset the count-rate history too (only the automatic
                    # hysteresis-cycle reset below leaves it alone). Without this,
                    # old samples from before the clear (with elapsed-time x-values
                    # up to whatever the prior session reached) stayed in the
                    # history while new samples restarted from ~0 - Plotly draws
                    # points in array order, not sorted by x, so that produced a
                    # corrupted line jumping backward mid-plot.
                    self.clear_cps_history()
                    self.last_ml_result = None
                    self.current_isotope_id = "Accumulating Counts..."
                    continue
                
                # Read hardware live-time straight from the active survey session registers
                survey_timers = await asyncio.to_thread(self._call_hw, self.daq_device.timers_read)
                self.survey_hardware_live_time_ms = float(survey_timers.get("tmr_c", 0))
                self.survey_elapsed_seconds = int(self.survey_hardware_live_time_ms / 1000)
                # tmr_a (real time) is read separately from live time - the two
                # are expected to differ whenever there's dead time during the
                # survey, so build_riid_download_zip() must not conflate them.
                self.survey_hardware_real_time_ms = float(survey_timers.get("tmr_a", self.survey_hardware_live_time_ms) or self.survey_hardware_live_time_ms)
                
                hardware_spectrum_array = await asyncio.to_thread(self._call_hw, self.daq_device.read_spectrum)
                if hardware_spectrum_array:
                    if previous_spectrum and len(previous_spectrum) == len(hardware_spectrum_array):
                        self.live_spectrum = [b + h for b, h in zip(previous_spectrum, hardware_spectrum_array)]
                    else:
                        self.live_spectrum = hardware_spectrum_array
                    
                total_counts = sum(self.live_spectrum) if self.live_spectrum else 0
                self.status_text = f"Survey Active ({self.survey_elapsed_seconds}s). Total Counts: {total_counts}"
                
                # Instantaneous count rate = counts accumulated SINCE the
                # last poll, divided by the time elapsed since that poll - distinct
                # from the existing cumulative-average CPS shown in the plot legend,
                # which smooths out over the whole session instead of showing recent
                # activity.
                live_time_s = self.survey_hardware_live_time_ms / 1000.0
                delta_counts = total_counts - self._prev_survey_counts
                delta_time_s = live_time_s - self._prev_survey_elapsed_s
                if delta_time_s > 0:
                    instantaneous_cps = max(delta_counts, 0) / delta_time_s
                    self.cps_history.append((self._cps_history_time_offset_s + live_time_s, instantaneous_cps, 'survey'))
                self._prev_survey_counts = total_counts
                self._prev_survey_elapsed_s = live_time_s
                
                # The auto-reset trigger is the PEAK SINGLE CHANNEL of the
                # background-subtracted spectrum - the exact same metric
                # MlInference itself checks against min_counts before
                # attempting classification, not the total/integral spectrum
                # count. Reuses compute_background_subtracted_spectrum() (the
                # same method backing the "Spectrum - Background"
                # visualization) rather than a separate implementation.
                default_bg_ms = self.DEFAULT_BG_TARGET_TIME_S * 1000
                bg_ms = float(getattr(self, 'bg_hardware_live_time_ms', default_bg_ms) or default_bg_ms)
                subtracted_spectrum = self.compute_background_subtracted_spectrum(
                    spectrum_data=self.live_spectrum, spectrum_live_time_s=live_time_s,
                    bg_data=self.background_spectrum, bg_live_time_s=bg_ms / 1000.0
                )
                peak_channel_value = float(max(subtracted_spectrum)) if subtracted_spectrum else 0.0
                
                # Sliding-window instantaneous rate sample (counts
                # accumulated in the peak channel SINCE the last poll, divided
                # by the time since that poll) - the same delta-based pattern
                # cps_history above uses, so the rate estimate stays reactive
                # to a genuine change instead of a cumulative average that
                # gets progressively more sluggish the longer the cycle runs.
                delta_peak = peak_channel_value - self._prev_peak_channel_value
                delta_time_peak = live_time_s - self._prev_peak_channel_elapsed_s
                if delta_time_peak > 0:
                    instantaneous_peak_rate = max(delta_peak, 0) / delta_time_peak
                    self._peak_channel_rate_history.append(instantaneous_peak_rate)
                self._prev_peak_channel_value = peak_channel_value
                self._prev_peak_channel_elapsed_s = live_time_s
                
                if self.auto_hysteresis_enabled:
                    # Recomputed every tick and stored back into
                    # max_counts_limit, so the sidebar's read-only display (and
                    # any other code reading this attribute) shows the CURRENT
                    # effective value, not a stale one.
                    self.max_counts_limit = self._compute_dynamic_hysteresis_threshold()
                effective_threshold = self.max_counts_limit
                
                if peak_channel_value >= effective_threshold:
                    mode_label = "auto" if self.auto_hysteresis_enabled else "manual"
                    logger.warning(f"[SURVEY_RUN] Peak channel [{peak_channel_value:.0f} cts] hit hysteresis threshold [{effective_threshold} cts] ({mode_label}). Resetting on-board buffer (no DPP resend)...")
                    
                    try: await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_stop)
                    except: pass
                    
                    await asyncio.to_thread(self._call_hw, self.daq_device.clear_spectrum)
                    await asyncio.to_thread(self._call_hw, self.daq_device.timers_reset)
                    await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_start)
                    
                    previous_spectrum = []
                    # Bank the elapsed time so far into the offset BEFORE zeroing the
                    # hardware timer below - this is what keeps the count-rate
                    # plot's x-axis monotonically increasing across this automatic
                    # reset (the history itself is intentionally preserved, per
                    # request - only an explicit CLEAR button resets it).
                    self._cps_history_time_offset_s += self.survey_hardware_live_time_ms / 1000.0
                    self.survey_elapsed_seconds = 0
                    self.survey_hardware_live_time_ms = 0.0
                    self.survey_hardware_real_time_ms = 0.0
                    self._prev_survey_counts = 0
                    self._prev_survey_elapsed_s = 0.0
                    self._prev_peak_channel_value = 0.0
                    self._prev_peak_channel_elapsed_s = 0.0
                    self._ml_trigger_fired_this_cycle = False
                    self.current_isotope_id = "Buffer Reset. Re-accumulating..."
                    continue
                
                # Recomputed every tick from the current peak-channel rate and
                # applied directly to MlInference, so the classification
                # attempt right below always uses the current effective
                # value - lower than DEFAULT_ML_MIN_COUNTS for a faint
                # source, equal to it for anything reaching that comfortably
                # within budget. Only while auto mode is on AND the pipeline
                # hasn't yet been triggered this cycle - once the peak
                # channel first reaches min_counts (the pipeline actually
                # attempts a real classification instead of "not enough
                # counts"), min_counts freezes at that value for the rest of
                # this cycle. Without this, min_counts could keep drifting
                # after the pipeline already started classifying - if it ever
                # drifted back UP above the current peak, the pipeline would
                # flip back to "not enough counts" mid-cycle even though the
                # peak channel itself only ever increases within a cycle,
                # which would be a confusing, unstable result to show. The
                # hysteresis reset threshold above is unaffected by this and
                # keeps adapting every tick regardless - it's explicitly
                # meant to keep tracking the current count-rate trend even
                # after min_counts has frozen.
                if self.auto_hysteresis_enabled and not self._ml_trigger_fired_this_cycle:
                    self.ml_inference.update_min_counts(self._compute_effective_ml_min_counts())
                
                if not self._ml_trigger_fired_this_cycle and peak_channel_value >= self.ml_inference.get_min_counts():
                    self._ml_trigger_fired_this_cycle = True
                
                self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum, self.survey_elapsed_seconds)
                    
        except Exception as e:
            logger.error(f"[HARDWARE] Continuous survey thread encountered an exception: {e}", exc_info=True)
            self.status_text = f"Survey Error: {e}"; self.set_state('IDLE')
        finally:
            # Must live in `finally`, not right after the while loop, so it also
            # runs on task cancellation - normal loop exit, an error above, OR
            # STOP (stop_execution() calls _main_loop_task.cancel(), which throws
            # CancelledError into whatever await this coroutine is suspended on,
            # almost always asyncio.sleep(1.0) mid-poll). CancelledError is a
            # BaseException, so it skips the `except Exception` above entirely.
            # Without this stop call here, the hardware keeps physically running
            # after STOP: it keeps accumulating real counts (later silently
            # wiped by the next START's forced BRAM-clear) AND keeps
            # incrementing Timer C the whole time acquisition sits "stopped" -
            # inflating the elapsed time relative to true counts.
            try: await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_stop)
            except: pass
            try: await asyncio.to_thread(self._call_hw, self.daq_device.close)
            except: pass
            logger.info("[SURVEY_RUN] Shared master loop context released safely.")


    def _execute_ml_pipeline(self, raw_spectrum: list[int], live_time : int) -> str:
        """Executes ML pipeline on live spectrum data.
        
        MlInference.inference_pipeline() now returns the FULL
        per-class probability breakdown (all classes, not just detected ones) -
        stored here in self.last_ml_result for the RIID results panel's Class
        Probabilities bar chart / Detected Isotopes / Avg Confidence cards.
        current_isotope_id remains a plain string for the simple status uses
        elsewhere (BG recording, accumulating, standby, etc.)."""
        result = self.ml_inference.inference_pipeline(spectrum_data=raw_spectrum, spectrum_live_time=live_time)
        
        if isinstance(result, dict):
            self.last_ml_result = result
            detected = {k: v for k, v in result.items() if v > self.ml_inference.CLASSIFICATION_THRESHOLD}
            
            # Also logs the identification result for an audit trail (the GUI
            # already displays it, but doesn't otherwise get recorded). Only
            # fires when the detected set actually changes (a new isotope
            # appears, the set changes, or it clears back to nothing), not
            # every ~1s poll tick, which would otherwise spam an identical
            # line throughout a long survey.
            current_detection_key = frozenset(detected.keys())
            if current_detection_key != self._last_logged_detection:
                if detected:
                    summary = ", ".join(f"{name} ({conf * 100:.1f}%)" for name, conf in detected.items())
                    logger.warning(f"[ML_DETECTION] Isotope(s) identified: {summary}")
                elif self._last_logged_detection:
                    # Only log the "cleared" transition if a detection had
                    # previously been logged - avoids a spurious "nothing
                    # detected" line the very first time inference runs.
                    logger.warning("[ML_DETECTION] No isotope currently exceeds the detection threshold (previous detection cleared).")
                self._last_logged_detection = current_detection_key
            
            if detected:
                return " + ".join(detected.keys())
            return "No isotope exceeded the detection threshold"
        
        # Plain status string (e.g. MlInference.STR_NOT_ENOUGH_COUNTS) - no
        # class breakdown available for this attempt.
        self.last_ml_result = None
        return result

    def set_ml_classification_threshold(self, new_threshold: float):
        """Passthrough to MlInference.update_classification_threshold() - the
        entry point the GUI's Detection Threshold slider calls,
        so the view layer doesn't need to reach into self.ml_inference
        directly."""
        self.ml_inference.update_classification_threshold(new_threshold)

    def set_ml_min_counts(self, new_min_counts: int):
        """Directly sets MlInference's min_counts, called by the GUI's ML
        trigger slider - only ever shown/usable in manual mode (see
        auto_hysteresis_enabled), so this always applies immediately with no
        adaptation. In auto mode, the poll loop recomputes and applies the
        effective value itself every tick instead (see
        _compute_effective_ml_min_counts), and this slider isn't shown at
        all.

        In offline mode there's no running survey loop to pick this change
        up on its own next tick, so classification is re-run immediately
        against the already-loaded spectrum instead."""
        self.ml_inference.update_min_counts(int(new_min_counts))
        if self.offline_mode and self.live_spectrum:
            self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum, self.survey_elapsed_seconds)

    def set_auto_hysteresis_enabled(self, enabled: bool):
        """Toggles automatic mode for BOTH the hysteresis
        reset threshold and the ML trigger threshold (min_counts) together -
        called by the GUI's "Automatic hysteresis" checkbox."""
        self.auto_hysteresis_enabled = bool(enabled)
        if enabled:
            # Baseline immediately to the default rather than leaving
            # whatever the manual slider last set - the poll loop only
            # recomputes this during an active survey, so without this a
            # switch to auto while idle would leave the "auto" display
            # showing a stale manually-set value until the next survey starts.
            self.ml_inference.update_min_counts(self.DEFAULT_ML_MIN_COUNTS)
        logger.warning(f"[USER_ACTION] Operator {'enabled' if enabled else 'disabled'} automatic hysteresis reset.")

    def set_manual_hysteresis_threshold(self, new_threshold: int):
        """Sets the operator's manual peak-single-channel-count
        threshold, used only while auto_hysteresis_enabled is False."""
        self.max_counts_limit = int(new_threshold)

    def set_ml_model(self, model_name: str) -> tuple:
        """Swaps the active ML model at runtime (cnn_multilabel /
        cnn_deep). Reconstructs self.ml_inference with the new model, since
        MlInference doesn't support hot-swapping its underlying model file -
        but carries the current background data, classification threshold,
        and minimum-counts trigger over to the new instance, so switching
        models doesn't silently reset any of those.
        
        Only meaningful while idle - the model choice affects what
        _execute_ml_pipeline() returns (including the label SET itself, since
        cnn_deep and cnn_multilabel have different classes), so switching
        mid-survey could produce a confusing mix of old- and new-model
        results. The GUI is expected to only enable this control while
        stopped, but this method also guards defensively.

        In offline mode there's no running survey loop to pick this change
        up on its own next tick, so classification is re-run immediately
        against the already-loaded spectrum under the new model instead.

        Returns:
            (bool, str): (success, message) for the UI to display.
        """
        if self.state != 'IDLE':
            return False, "Cannot switch ML models while a survey/recording is active."
        
        try:
            current_threshold = self.ml_inference.CLASSIFICATION_THRESHOLD
            current_min_counts = self.ml_inference.get_min_counts()
            bg_live_time_s = float(self.bg_hardware_live_time_ms or 0.0) / 1000.0
            new_inference = MlInference(
                ml_model_name=model_name,
                min_counts=current_min_counts,
                bkgnd_data=self.background_spectrum,
                bkgnd_live_time=bg_live_time_s
            )
            new_inference.update_classification_threshold(current_threshold)
            self.ml_inference = new_inference
            self.ml_model_name = model_name
            # Any previous inference result belonged to the old model's label
            # set - stale/incompatible with the new one (cnn_deep and
            # cnn_multilabel don't share the same classes), so clear it
            # rather than risk displaying mismatched class names.
            self.last_ml_result = None
            if self.offline_mode and self.live_spectrum:
                self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum, self.survey_elapsed_seconds)
            logger.warning(f"[USER_ACTION] Operator switched ML model to '{model_name}'.")
            return True, f"Switched to {model_name}."
        except Exception as e:
            logger.error(f"[SERVICE] Failed to switch ML model to '{model_name}': {e}", exc_info=True)
            return False, f"Failed to switch model: {e}"

    def compute_background_subtracted_spectrum(self, spectrum_data: list, spectrum_live_time_s: float, bg_data: list, bg_live_time_s: float) -> list:
        """Reuses
        MLPreprocessing.subtract_background() - the exact same background
        subtraction step MlInference.inference_pipeline() runs before feeding
        a spectrum to the model - instead of maintaining a second, separate
        subtraction implementation in the view layer. This means the
        visualization is a true representation of what the classifier itself
        reasons over, and can't silently drift out of sync with the ML
        pipeline's own subtraction behavior over time.
        
        A fresh MLPreprocessing instance is constructed per call - this is
        cheap (it just stores a few int/float config values, no model loading
        or I/O), unlike constructing a fresh MlInference.
        
        min_counts=0 (not the ML pipeline's own value of 20) - this call is
        purely for display. The spectrum must stay visible even when the ML
        pipeline itself declines to run inference due to insufficient counts;
        min_counts here only controls a log warning inside subtract_background
        about the subtraction being statistically unreliable, and that warning
        shouldn't fire just because the operator is looking at a low-count
        spectrum that isn't being classified yet.
        
        Args:
            spectrum_data (list): Raw spectrum counts.
            spectrum_live_time_s (float): Spectrum's live time, in SECONDS
                (subtract_background expects seconds, unlike the hardware
                timers elsewhere in this file which report milliseconds).
            bg_data (list): Raw background counts.
            bg_live_time_s (float): Background's live time, in SECONDS.
        
        Returns:
            list: Background-subtracted spectrum, negative values clipped to
            0. If no usable background is available, subtract_background
            itself falls back to returning the raw spectrum unchanged.
        """
        preprocessor = MLPreprocessing(min_counts=0)
        result = preprocessor.subtract_background(
            spectrum_data=spectrum_data, spectrum_live_time=spectrum_live_time_s,
            bkgnd_data=bg_data or [], bkgnd_live_time=bg_live_time_s
        )
        return result.tolist()

    def clear_cps_history(self):
        """Clears the count-rate plot's rolling history.
        Triggered by either its own dedicated Clear button OR the spectrum's
        own CLEAR (both are explicit "start fresh" actions) - only the
        automatic hysteresis-cycle buffer reset leaves the history alone, so
        the rate profile stays continuous across THAT event specifically.
        Also re-baselines both delta trackers (survey and background) and the
        monotonic time offset so the next sample starts fresh rather than
        computing a spurious delta, or plotting at a stale x-position, against
        pre-clear state."""
        self.cps_history.clear()
        self._prev_survey_counts = 0
        self._prev_survey_elapsed_s = 0.0
        self._prev_bg_counts = 0
        self._prev_bg_elapsed_s = 0.0
        self._cps_history_time_offset_s = 0.0
        # Same explicit-clear-only rule as cps_history above - an
        # automatic hysteresis-cycle reset leaves this alone (see the
        # buffer-reset branch), only an explicit CLEAR/RESTART wipes it.
        self._peak_channel_rate_history.clear()
        self._prev_peak_channel_value = 0.0
        self._prev_peak_channel_elapsed_s = 0.0
        self._ml_trigger_fired_this_cycle = False
        logger.warning("[USER_ACTION] Operator cleared the count-rate plot history.")

    def _compute_dynamic_hysteresis_threshold(self) -> int:
        """Additive model, not a clamped
        multiplicative floor. See the HYSTERESIS_* class constants above for
        the sliding-window averaging. This method's own change is structural:
        
            threshold = DEFAULT_ML_MIN_COUNTS + avg_peak_channel_rate * TARGET_TIME_S
        
        instead of the previous clamp(min_counts * MULT, rate * TARGET_TIME_S
        * MULT, ceiling). The clamped-floor version had a real flaw: in the
        floor-limited regime (faint sources, where the proportional term
        never exceeds the floor), the fraction of the cycle spent actually
        SHOWING a result works out to exactly (MULT-1)/MULT - a constant
        RATIO, regardless of how faint the source is. A faint source that
        takes 2 minutes to reach min_counts got the same lousy ~33% show-
        result window (at MULT=1.5) as one that takes 2 seconds - raising
        MULT further would help, but it's still bounded by the SAME ratio
        problem, whether the min_counts->floor relationship is linear or a
        non-linear function of min_counts (e.g. a power law) - the ratio is
        determined by the floor-to-min_counts relationship itself, not by
        whether that relationship happens to be linear.
        
        The additive form sidesteps this: since rate cancels out algebraically
        in (threshold - BASE) / rate = TARGET_TIME_S, EVERY source gets an
        observation window of exactly TARGET_TIME_S seconds after crossing
        BASE, regardless of activity - not a fixed fraction of a rate-
        dependent wait, but a fixed duration, full stop.
        
        BASE is DEFAULT_ML_MIN_COUNTS specifically, NOT
        self.ml_inference.get_min_counts() - a later change made that value
        itself dynamically adapt down for a faint source (see
        _compute_effective_ml_min_counts), which would otherwise couple two
        independently-noisy adaptive systems together (both ultimately
        derived from the same peak-channel-rate trend), undermining the
        constant-observation-window guarantee this method exists to provide.
        Using the fixed default instead restores that guarantee AND
        strengthens it for a faint source specifically: since the actual
        effective min_counts is always <= DEFAULT_ML_MIN_COUNTS, the
        observation window becomes >= TARGET_TIME_S - strictly longer, never
        shorter, exactly where "still acting too fast" was reported.
        
        Returns:
            int: the peak-single-channel-count threshold at which the survey
            buffer should auto-reset, recomputed fresh each call (once per
            poll tick).
        """
        if not self._peak_channel_rate_history:
            # No rate samples yet (e.g. the very first tick(s) of a fresh
            # cycle, where rate is undefined) - fall back to a small fixed
            # margin above the default rather than a stale or zero
            # threshold, so even the first reset happens at a sane bound.
            # Only ever matters for a tick or two before the real formula
            # above takes over.
            return int(self.DEFAULT_ML_MIN_COUNTS * self.HYSTERESIS_FLOOR_MULTIPLIER)
        
        avg_peak_channel_rate = sum(self._peak_channel_rate_history) / len(self._peak_channel_rate_history)
        threshold = self.DEFAULT_ML_MIN_COUNTS + (avg_peak_channel_rate * self.HYSTERESIS_TARGET_TIME_S)
        return int(min(threshold, self.HYSTERESIS_CEILING_COUNTS))

    def _compute_effective_ml_min_counts(self) -> int:
        """See ML_TRIGGER_ABSOLUTE_FLOOR's docstring above for the full
        reasoning. Reuses the same sliding-window peak-channel-rate history
        as _compute_dynamic_hysteresis_threshold() (both track the same
        underlying quantity), applied to a different formula:
        
            effective = clamp(ABSOLUTE_FLOOR, avg_peak_channel_rate *
                               TIME_BUDGET_S, DEFAULT_ML_MIN_COUNTS)
        
        Only called in auto mode (see auto_hysteresis_enabled) - manual mode
        applies the operator's slider value directly instead, with no
        adaptation. A source fast enough to reach DEFAULT_ML_MIN_COUNTS
        within TIME_BUDGET_S uses that full default unchanged (preserving
        good statistics for already-fine sources); a slower one gets a
        proportionally lower effective threshold, bounded below by
        ABSOLUTE_FLOOR.
        
        Returns:
            int: the min_counts value to apply to MlInference this tick.
        """
        if not self._peak_channel_rate_history:
            # No rate samples yet - use the default directly rather than
            # guessing; the real formula takes over from the next tick once
            # a rate is known.
            return self.DEFAULT_ML_MIN_COUNTS
        
        avg_peak_channel_rate = sum(self._peak_channel_rate_history) / len(self._peak_channel_rate_history)
        rate_bounded = avg_peak_channel_rate * self.ML_TRIGGER_TIME_BUDGET_S
        return int(max(self.ML_TRIGGER_ABSOLUTE_FLOOR, min(rate_bounded, self.DEFAULT_ML_MIN_COUNTS)))


    def start_batch_recording(self, target_time: int, total_runs: int, prefix: str):
        """Assembles automated structural script loops mapping data files."""
        logger.warning(f"[DAQ_ACTION] Operator triggered automated multi-run batch recording -> runs={total_runs}")
        if self.state != 'IDLE': return
        self.batch_target_time = target_time; self.batch_total_runs = total_runs; self.batch_prefix = prefix
        self.set_state('BATCH_RECORDING')
        self._main_loop_task = asyncio.create_task(self._batch_recording_worker_loop())

    async def _batch_recording_worker_loop(self):
        """Automated file system serialization thread worker array loop.
        
        Every self.daq_device.* call below is offloaded via
        asyncio.to_thread() - see _continuous_survey_sequence's docstring for
        the full reasoning (synchronous serial I/O blocking the entire event
        loop, including the UI's own tick timer, for its full duration on
        every poll tick)."""
        # Every run in this batch shares the same target duration, so the hardware
        # Preset register only needs to be set once here - not per run. This gives
        # the board's own clock millisecond-precision control over when Timer C
        # (live time) stops, rather than relying purely on the ~1s software poll
        # below to detect "elapsed >= target" after the fact.
        preset_ok = self._set_timers_preset(self.batch_target_time * 1000)
        if not preset_ok:
            logger.warning("[BATCH_WORKER] Hardware timer preset could not be set - falling back to software-only timing (expect some overshoot past the target duration).")
        
        try:
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
                    await asyncio.to_thread(self._call_hw, self.daq_device.open)
                    await asyncio.to_thread(self._call_hw, self.daq_device.clear_spectrum)
                    await asyncio.to_thread(self._call_hw, self.daq_device.timers_reset)
                    await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_start)
                except Exception as e:
                    logger.error(f"[BATCH_WORKER] Hardware access dropped during sequence initiation step: {e}", exc_info=True)
                    self.batch_status_text = f"Hardware error: {e}"; break

                try:
                    while self.batch_elapsed_seconds < self.batch_target_time and self.state == 'BATCH_RECORDING':
                        await asyncio.sleep(1.0)
                        if not self.verify_runtime_hardware_safety(): break
                        batch_timers = await asyncio.to_thread(self._call_hw, self.daq_device.timers_read)
                        self.batch_elapsed_seconds = int(batch_timers["tmr_c"] / 1000)
                        self.batch_spectrum = await asyncio.to_thread(self._call_hw, self.daq_device.read_spectrum)
                        self.batch_status_text = f"Run [{self.batch_current_run}/{self.batch_total_runs}] -> Live-Time: {self.batch_elapsed_seconds}/{self.batch_target_time}s"

                    if self.state != 'BATCH_RECORDING':
                        return

                    # Stop acquisition immediately so the on-board timers/spectrum freeze at
                    # this exact moment. Without this, acquisition keeps running physically
                    # while we perform the final reads below, so the reported live/real time
                    # drifts well past the requested target the longer those reads take.
                    try:
                        await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_stop)
                    except Exception as e:
                        logger.error(f"[BATCH_WORKER] Failed to stop acquisition cleanly before final read: {e}", exc_info=True)

                    final_spectrum = await asyncio.to_thread(self._call_hw, self.daq_device.read_spectrum)

                    # Final timer read for the most accurate final live/real time values
                    # (used by both the .json and .spe metadata below). Safe to do now since
                    # acquisition is already stopped and the registers are no longer moving.
                    try:
                        final_timers = await asyncio.to_thread(self._call_hw, self.daq_device.timers_read)
                    except Exception:
                        final_timers = {}

                    final_live_ms = float(final_timers.get("tmr_c", self.batch_elapsed_seconds * 1000) or self.batch_elapsed_seconds * 1000)
                    final_real_ms = float(final_timers.get("tmr_a", final_live_ms) or final_live_ms)
                    final_live_s = final_live_ms / 1000.0
                    final_real_s = final_real_ms / 1000.0

                    time_now = datetime.now(timezone.utc)
                    os.makedirs(self.OUTPUT_FOLDER, exist_ok=True)
                    file_stamp = time_now.strftime("%Y%m%d_%H%M%S")
                    base_filepath = os.path.join(self.OUTPUT_FOLDER, f"{file_stamp}_{self.system.serial_number}_{self.batch_prefix}_run{run_idx:04d}")
                    spectrum_id = f"RUN_{run_idx}"

                    # Single source of truth for both file formats below.
                    metadata = self._build_spectrum_metadata(
                        num_channels=len(final_spectrum), run_idx=run_idx, live_time_s=final_live_s, real_time_s=final_real_s
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
                    try: await asyncio.to_thread(self._call_hw, self.daq_device.data_acquisition_stop)
                    except: pass
                    try: await asyncio.to_thread(self._call_hw, self.daq_device.close)
                    except: pass

            self.set_state('IDLE'); self.batch_status_text = "Batch measurements finished successfully."
        finally:
            # Every run above resets the shared hardware live-time timer
            # (timers_reset()), the same way _bg_recording_sequence's own
            # session does - which breaks the RIID survey's STOP -> START
            # "hardware timer persists" continuity assumption out from under
            # it if a batch job runs in between. Mirrors that method's own
            # finally block for exactly this reason, so every exit path here
            # (normal completion, an aborted run, or STOP-triggered task
            # cancellation) leaves things in a state the next survey session
            # can trust:
            #   1. Clear the stale self.live_spectrum left over from
            #      whatever survey ran before this batch job - otherwise the
            #      next survey START wrongly treats it as a prior
            #      accumulation to "resume" (skipping its own timers_reset())
            #      even though the hardware timer no longer matches it.
            #   2. Raise the count-rate plot's x-axis offset to at least
            #      whatever was last actually plotted, so the next
            #      survey/background session - which starts counting from a
            #      freshly-reset live-time of 0 - can never land BEHIND
            #      already-plotted points and corrupt the line.
            self.live_spectrum = []
            if self.cps_history:
                self._cps_history_time_offset_s = max(self._cps_history_time_offset_s, self.cps_history[-1][0])

    def _build_spectrum_metadata(self, num_channels: int, run_idx: int, live_time_s: float, real_time_s: float) -> dict:
        """Assembles the full metadata block attached to a recorded spectrum. This is
        the single source of truth reused by both the .json and .spe writers, so the
        two file formats always carry identical information."""
        prof = self.system.hw_profile
        rt = self.system.runtime_metadata
        vga_gain = float(prof.get("vga_gain_coarse", 6.0) or 6.0)
        return {
            "Material type": rt.get("Material type", "Source"),
            "Material form": rt.get("Material form", "point"),
            # Each entry may carry its own "Notes" key (per-source, entered when the
            # source was appended in the GUI) - deliberately NOT persisted to
            # sources.json, only present here in the recorded spectrum's metadata.
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
            "Spectrum acquisition date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "Spectrum live time (s)": live_time_s,
            "Spectrum real time (s)": real_time_s,
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

        def sanitize_spe_text(value) -> str:
            """Collapses to a single ASCII-safe line for embedding in the .spe
            file's line-based $SPE_REM block. Free-text fields (e.g. a per-source
            Notes entry) could otherwise contain newlines or non-ASCII characters
            that would break the line format or crash the ascii-encoded write."""
            text = str(value if value is not None else "")
            text = text.replace('\r', ' ').replace('\n', ' | ')
            return text.encode('ascii', errors='replace').decode('ascii')

        with open(f"{filepath_base}.spe", "w", encoding="ascii") as sf:
            sf.write(f"$SPEC_ID:\n{spectrum_id}\n")
            sf.write(f"$DATE_MEA:\n{time_now.strftime('%m/%d/%Y %H:%M:%S')}\n")
            sf.write(f"$MEAS_TIM:\n{live_time_s:.2f} {real_time_s:.2f}\n")
            sf.write("$SPE_REM:\n")
            sf.write(f"Material Type: {metadata['Material type']}\n")
            sf.write(f"Material Form: {metadata['Material form']}\n")
            if metadata['Sources']:
                for i, src in enumerate(metadata['Sources']):
                    # Per-source "Notes" (if present) rides along automatically here -
                    # it's just another key in each source's dict, sanitized like
                    # every other field so it can't break the line format.
                    fields = ", ".join(f"{k}={sanitize_spe_text(v)}" for k, v in src.items())
                    sf.write(f"Source[{i}]: {fields}\n")
            else:
                sf.write("Sources: none\n")
            if metadata['Attenuators']:
                for i, att in enumerate(metadata['Attenuators']):
                    fields = ", ".join(f"{k}={sanitize_spe_text(v)}" for k, v in att.items())
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

    def save_background_spectrum(self, filename: str, save_json: bool = True, save_spe: bool = True) -> tuple[bool, str]:
        """Persists the latest recorded background spectrum to disk,
        in JSON and/or SPE format as requested. Reuses the exact same
        _build_spectrum_metadata()/_write_spe_file() pipeline as batch
        recordings instead of duplicating any
        serialization logic, so detector/calibration/source metadata is
        included identically to how batch spectra files are stored.
        
        "Material type" is forced to "background"
        on a COPY of the metadata used for this save only - the live
        runtime_metadata dict (used elsewhere for batch/sources) is left
        untouched.
        
        Args:
            filename (str): Desired base filename (without extension), as
                chosen by the operator in the save prompt.
            save_json (bool): Whether to write the .json file.
            save_spe (bool): Whether to write the .spe file.
        
        Returns:
            (bool, str): (success, message) - message is a short summary of
            what was saved, or an error description for the UI to display.
        """
        if not self.background_spectrum:
            return False, "No background spectrum has been recorded yet."
        if not save_json and not save_spe:
            return False, "Select at least one output format (JSON and/or SPE)."
        
        safe_filename = "".join(c for c in str(filename or "").strip() if c.isalnum() or c in ("_", "-", "."))
        if not safe_filename:
            return False, "Enter a valid file name."
        
        try:
            os.makedirs(SPECTRA_BACKGROUND_DIR, exist_ok=True)
            base_filepath = os.path.join(SPECTRA_BACKGROUND_DIR, safe_filename)
            
            live_time_s = float(self.bg_hardware_live_time_ms or 0.0) / 1000.0
            # Measured independently from live_time_s (see
            # _bg_recording_sequence / load_background_spectrum) - expected
            # to differ from live time whenever there's any dead time during
            # the capture.
            real_time_s = float(self.bg_hardware_real_time_ms or 0.0) / 1000.0
            
            metadata = self._build_spectrum_metadata(
                num_channels=len(self.background_spectrum), run_idx=0,
                live_time_s=live_time_s, real_time_s=real_time_s
            )
            # Mark this saved file's Material type/form for a background capture,
            # without mutating the live runtime_metadata dict (used elsewhere for
            # batch/sources).
            metadata["Material type"] = "background"
            metadata["Material form"] = "Environmental"
            
            spectrum_id = f"BG_{safe_filename}"
            time_now = datetime.now(timezone.utc)
            saved_files = []
            
            if save_json:
                with open(f"{base_filepath}.json", "w", encoding="utf-8") as jf:
                    json.dump({"id": spectrum_id, "metadata": metadata, "data": self.background_spectrum}, jf, indent=2)
                saved_files.append(f"{safe_filename}.json")
            
            if save_spe:
                self._write_spe_file(
                    filepath_base=base_filepath, spectrum_id=spectrum_id, spectrum=self.background_spectrum,
                    metadata=metadata, live_time_s=live_time_s, real_time_s=real_time_s, time_now=time_now
                )
                saved_files.append(f"{safe_filename}.spe")
            
            logger.warning(f"[USER_ACTION] Operator saved background spectrum: {', '.join(saved_files)} -> {SPECTRA_BACKGROUND_DIR}")
            return True, f"Saved {' and '.join(saved_files)}"
        except Exception as e:
            logger.error(f"[SERVICE] Failed to save background spectrum: {e}", exc_info=True)
            return False, f"Failed to save background spectrum: {e}"

    def build_riid_download_zip(self, filename: str) -> tuple:
        """Persists the current spectrum shown in the RIID view
        (self.live_spectrum) to data/spectra/riid/ under the given base
        filename, then bundles it together with the current background
        spectrum, both in .json and .spe formats, into a single .zip for
        download.

        Only the RIID spectrum is persisted here. The background is NOT
        re-written to data/spectra/background/ - that already has its own
        explicit "Store Background Spectrum" action; re-saving it here on
        every RIID download would silently pile up duplicate background files.
        It's serialized in-memory (via a throwaway temp file, reusing the
        already-tested _write_spe_file logic instead of duplicating it) purely
        for inclusion in this zip.

        Args:
            filename (str): Desired base filename (without extension), as
                chosen by the operator in the save prompt.

        Returns:
            (bool, str, bytes|None, str|None): (success, message, zip_bytes,
            base_filename). base_filename is the sanitized name used for
            both the persisted RIID files and the returned zip's contents, so
            the caller can name the downloaded zip consistently with what was
            actually saved to disk.
        """
        if not self.live_spectrum:
            return False, "No spectrum currently shown in the RIID view.", None, None
        if not self.background_spectrum:
            return False, "No background spectrum available - record or load one first.", None, None

        safe_filename = "".join(c for c in str(filename or "").strip() if c.isalnum() or c in ("_", "-", "."))
        if not safe_filename:
            return False, "Enter a valid file name.", None, None

        time_now = datetime.now(timezone.utc)

        try:
            os.makedirs(SPECTRA_RIID_DIR, exist_ok=True)
            riid_base = os.path.join(SPECTRA_RIID_DIR, safe_filename)
            
            # Measured independently from live time (see
            # _continuous_survey_sequence, which reads tmr_a separately).
            riid_live_s = float(self.survey_hardware_live_time_ms or 0.0) / 1000.0
            riid_real_s = float(self.survey_hardware_real_time_ms or 0.0) / 1000.0
            riid_metadata = self._build_spectrum_metadata(
                num_channels=len(self.live_spectrum), run_idx=0,
                live_time_s=riid_live_s, real_time_s=riid_real_s
            )
            riid_spectrum_id = f"RIID_{safe_filename}"
            
            with open(f"{riid_base}.json", "w", encoding="utf-8") as jf:
                json.dump({"id": riid_spectrum_id, "metadata": riid_metadata, "data": self.live_spectrum}, jf, indent=2)
            self._write_spe_file(
                filepath_base=riid_base, spectrum_id=riid_spectrum_id, spectrum=self.live_spectrum,
                metadata=riid_metadata, live_time_s=riid_live_s, real_time_s=riid_real_s, time_now=time_now
            )
            logger.warning(f"[USER_ACTION] Operator downloaded RIID spectrum - saved to {riid_base}.json / .spe")
            
            # Serialize the background in-memory for the zip (see docstring - not
            # persisted to data/spectra/background/ again here).
            bg_live_s = float(self.bg_hardware_live_time_ms or 0.0) / 1000.0
            bg_real_s = float(self.bg_hardware_real_time_ms or 0.0) / 1000.0
            bg_metadata = self._build_spectrum_metadata(
                num_channels=len(self.background_spectrum), run_idx=0,
                live_time_s=bg_live_s, real_time_s=bg_real_s
            )
            bg_metadata["Material type"] = "background"
            bg_metadata["Material form"] = "Environmental"
            bg_spectrum_id = f"BG_{safe_filename}"
            bg_json_bytes = json.dumps({"id": bg_spectrum_id, "metadata": bg_metadata, "data": self.background_spectrum}, indent=2).encode("utf-8")
            
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_base = os.path.join(tmpdir, "bg_temp")
                self._write_spe_file(
                    filepath_base=tmp_base, spectrum_id=bg_spectrum_id, spectrum=self.background_spectrum,
                    metadata=bg_metadata, live_time_s=bg_live_s, real_time_s=bg_real_s, time_now=time_now
                )
                with open(f"{tmp_base}.spe", "rb") as f:
                    bg_spe_bytes = f.read()
            
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(f"{riid_base}.json", arcname=f"{safe_filename}.json")
                zf.write(f"{riid_base}.spe", arcname=f"{safe_filename}.spe")
                zf.writestr(f"{safe_filename}_background.json", bg_json_bytes)
                zf.writestr(f"{safe_filename}_background.spe", bg_spe_bytes)
            buffer.seek(0)
            
            return True, f"Saved {safe_filename}.json and {safe_filename}.spe to data/spectra/riid/", buffer.getvalue(), safe_filename
        except Exception as e:
            logger.error(f"[SERVICE] Failed to build RIID download zip: {e}", exc_info=True)
            return False, f"Failed to save/package spectrum: {e}", None, None

    def list_available_background_files(self) -> list:
        """Lists .json/.spe files available in the background spectra folder
        (data/spectra/background/), for the "load pre-recorded background"
        picker. Returns bare filenames only (no path) - the file
        system location stays known only to the service layer, matching how
        save_background_spectrum() already keeps that internal."""
        try:
            if not os.path.isdir(SPECTRA_BACKGROUND_DIR):
                return []
            return sorted(
                f for f in os.listdir(SPECTRA_BACKGROUND_DIR)
                if f.lower().endswith(('.json', '.spe'))
            )
        except Exception as e:
            logger.error(f"[SERVICE] Failed to list background files: {e}", exc_info=True)
            return []

    def load_background_spectrum(self, filename: str) -> tuple:
        """Loads a pre-recorded background spectrum from a .json or .spe file
        in data/spectra/background/, as an alternative to
        recording a fresh one via start_background_recording(). The current
        "record new" flow is untouched by this - this is purely an additional
        path into the same self.background_spectrum/bg_hardware_live_time_ms
        state.
        
        "Including calibration": the file's own energy calibration (offset/
        linear/quadratic, as stored by _write_spe_file / _build_spectrum_metadata)
        is read and compared against the system's CURRENT hardware calibration.
        If they differ, the background is still loaded (the operator's call
        whether that's acceptable), but the mismatch is flagged in the returned
        message - since view_spectrum_id.py's _get_energy_axis() always renders
        the background trace using the CURRENT hw_profile calibration, a
        background recorded under different calibration settings would plot
        with a shifted/incorrect energy axis. This method does NOT overwrite
        the system's active calibration with the file's values - that would be
        a much more invasive, separate decision that this feature does not ask for.
        
        Returns:
            (bool, str): (success, message) - the message is either a summary
            (potentially including a calibration-mismatch warning) or an error
            description for the UI to display.
        """
        if self.state != 'IDLE':
            return False, "Cannot load a background while a survey/recording is active."
        if not filename:
            return False, "Select a background file first."
        
        filepath = os.path.join(SPECTRA_BACKGROUND_DIR, os.path.basename(filename))
        if not os.path.isfile(filepath):
            return False, "File not found."
        
        ext = os.path.splitext(filepath)[1].lower()
        try:
            if ext == '.json':
                spectrum, live_time_s, real_time_s, file_calib = self._parse_background_json(filepath)
            elif ext == '.spe':
                spectrum, live_time_s, real_time_s, file_calib = self._parse_background_spe(filepath)
            else:
                return False, "Unsupported file type - choose a .json or .spe file."
        except Exception as e:
            logger.error(f"[SERVICE] Failed to load background spectrum from {filepath}: {e}", exc_info=True)
            return False, f"Failed to read file: {e}"
        
        if not spectrum:
            return False, "File contains no spectrum data."
        
        self.background_spectrum = spectrum
        self.bg_hardware_live_time_ms = live_time_s * 1000.0
        self.bg_hardware_real_time_ms = real_time_s * 1000.0
        self.bg_accumulated_seconds = int(live_time_s)
        self.status_text = "Background Spectrum Ready"
        
        # Same downstream update a live BG recording already performs.
        self.ml_inference.update_bkgnd_data(new_bkgnd_data=self.background_spectrum, new_bkgnd_live_time=self.bg_accumulated_seconds)
        
        logger.warning(f"[USER_ACTION] Operator loaded pre-recorded background spectrum: {filepath}")
        
        current_calib = (
            float(self.system.hw_profile.get('calib_a0', 0.0)),
            float(self.system.hw_profile.get('calib_a1', 1.0)),
            float(self.system.hw_profile.get('calib_a2', 0.0)),
        )
        if file_calib and not all(abs(a - b) < 1e-6 for a, b in zip(file_calib, current_calib)):
            return True, (
                f"Loaded {os.path.basename(filepath)}, but its energy calibration "
                f"(a0={file_calib[0]:.5f}, a1={file_calib[1]:.5f}, a2={file_calib[2]:.5f}) "
                f"differs from the current hardware calibration - the background trace "
                f"is plotted using the CURRENT calibration and may not align correctly."
            )
        return True, f"Loaded {os.path.basename(filepath)}"

    def _parse_background_json(self, filepath: str) -> tuple:
        """Parses a background .json file (see save_background_spectrum) back
        into (spectrum, live_time_s, real_time_s, calibration_tuple). Requires
        both "Spectrum live time (s)" and "Spectrum real time (s)" to be
        present - a file missing either is rejected rather than silently
        backfilled, since a guessed value is worse than no value."""
        with open(filepath, "r", encoding="utf-8") as f:
            payload = json.load(f)
        spectrum = payload.get("data", [])
        metadata = payload.get("metadata", {})
        if "Spectrum live time (s)" not in metadata or "Spectrum real time (s)" not in metadata:
            raise ValueError("File is missing live/real time metadata.")
        live_time_s = float(metadata["Spectrum live time (s)"])
        real_time_s = float(metadata["Spectrum real time (s)"])
        calib = (
            float(metadata.get("Energy calibration offset (keV)", 0.0)),
            float(metadata.get("Energy calibration linear (keV/ch)", 1.0)),
            float(metadata.get("Energy calibration quadratic (keV/ch2)", 0.0)),
        )
        return spectrum, live_time_s, real_time_s, calib

    def _parse_background_spe(self, filepath: str) -> tuple:
        """Parses a background .spe file (see _write_spe_file) back into
        (spectrum, live_time_s, real_time_s, calibration_tuple). Reads
        $MEAS_TIM (live and real time), $MCA_CAL (calibration coefficients),
        and $DATA (channel counts) - the same sections _write_spe_file
        produces."""
        with open(filepath, "r", encoding="ascii", errors="replace") as f:
            lines = [ln.rstrip('\n').rstrip('\r') for ln in f.readlines()]

        spectrum = []
        live_time_s = 0.0
        real_time_s = 0.0
        calib = (0.0, 1.0, 0.0)

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line == "$MEAS_TIM:":
                # $MEAS_TIM holds "<live_time_s> <real_time_s>" (see
                # _write_spe_file). A file with only one value is rejected
                # rather than backfilled.
                parts = lines[i + 1].split()
                if len(parts) < 2:
                    raise ValueError("File is missing real time in $MEAS_TIM.")
                live_time_s = float(parts[0])
                real_time_s = float(parts[1])
                i += 2
                continue
            if line == "$MCA_CAL:":
                # Line i+1 is the coefficient count, line i+2 is the values themselves.
                coeff_values = [float(x) for x in lines[i + 2].split()]
                if len(coeff_values) >= 3:
                    calib = tuple(coeff_values[:3])
                i += 3
                continue
            if line == "$DATA:":
                # Line i+1 is the "start end" channel range; counts follow, one per
                # line, until the next $-prefixed section marker.
                i += 2
                while i < len(lines) and not lines[i].startswith('$'):
                    if lines[i].strip():
                        spectrum.append(int(float(lines[i].strip())))
                    i += 1
                continue
            i += 1

        return spectrum, live_time_s, real_time_s, calib

    def load_offline_spectrum(self, category: str, filename: str) -> tuple:
        """Loads a pre-recorded spectrum from any data/spectra/ category
        (background, batch, or riid) and analyzes it as if it were the
        current live spectrum, instead of pulling from the DAQ board.

        Reuses the same file parsers load_background_spectrum() does - the
        .json/.spe schema is shared across categories, only the meaning of
        the data differs. Requires a background to already be loaded, same
        precondition the live survey already enforces via the UI.

        Args:
            category (str): One of 'background', 'batch', 'riid'.
            filename (str): Bare filename (no path) within that category's folder.

        Returns:
            (bool, str): (success, message) - message is a summary
            (potentially including a calibration-mismatch warning, same as
            load_background_spectrum) or an error description for the UI.
        """
        if self.state != 'IDLE':
            return False, "Cannot load a spectrum while a survey/recording is active."
        if not self.background_spectrum:
            return False, "Load a background spectrum first."
        if not filename:
            return False, "Select a spectrum file first."

        folder = self.SPECTRA_CATEGORY_DIRS.get(category)
        if not folder:
            return False, f"Unknown category: {category}"

        filepath = os.path.join(folder, os.path.basename(filename))
        if not os.path.isfile(filepath):
            return False, "File not found."

        ext = os.path.splitext(filepath)[1].lower()
        try:
            if ext == '.json':
                spectrum, live_time_s, real_time_s, file_calib = self._parse_background_json(filepath)
            elif ext == '.spe':
                spectrum, live_time_s, real_time_s, file_calib = self._parse_background_spe(filepath)
            else:
                return False, "Unsupported file type - choose a .json or .spe file."
        except Exception as e:
            logger.error(f"[SERVICE] Failed to load offline spectrum from {filepath}: {e}", exc_info=True)
            return False, f"Failed to read file: {e}"

        if not spectrum:
            return False, "File contains no spectrum data."

        self.live_spectrum = spectrum
        self.survey_hardware_live_time_ms = live_time_s * 1000.0
        self.survey_hardware_real_time_ms = real_time_s * 1000.0
        self.survey_elapsed_seconds = int(live_time_s)
        self.offline_mode = True
        # Reuses the same "frozen survey" plotting path a STOPped live survey
        # already uses (trace gating, background time-normalization, CPS
        # calc all key off this) - a loaded static spectrum needs the exact
        # same treatment, just sourced from a file instead of a stopped DAQ
        # read. clear_survey_data() (RESTART) already resets this to False.
        self.survey_stopped_with_data = True
        self.set_auto_hysteresis_enabled(False)
        self.max_counts_limit = 2000  # slider max - "auto-reset to the maximum value"
        self.current_isotope_id = self._execute_ml_pipeline(self.live_spectrum, self.survey_elapsed_seconds)
        self.status_text = "Offline Analysis Ready"

        logger.warning(f"[USER_ACTION] Operator loaded offline analysis spectrum ({category}): {filepath}")

        current_calib = (
            float(self.system.hw_profile.get('calib_a0', 0.0)),
            float(self.system.hw_profile.get('calib_a1', 1.0)),
            float(self.system.hw_profile.get('calib_a2', 0.0)),
        )
        if file_calib and not all(abs(a - b) < 1e-6 for a, b in zip(file_calib, current_calib)):
            return True, (
                f"Loaded {os.path.basename(filepath)}, but its energy calibration "
                f"(a0={file_calib[0]:.5f}, a1={file_calib[1]:.5f}, a2={file_calib[2]:.5f}) "
                f"differs from the current hardware calibration - the spectrum "
                f"is plotted using the CURRENT calibration and may not align correctly."
            )
        return True, f"Loaded {os.path.basename(filepath)}"

    def list_spectra_files(self, category: str, ext_filter: str = 'ALL') -> list:
        """Lists files available for bulk download in a data/spectra/ category
        folder.
        
        Args:
            category (str): One of 'background', 'batch', 'riid'.
            ext_filter (str): 'ALL' (.json and .spe), 'JSON', or 'SPE'
                (case-insensitive).
        
        Returns:
            list: Sorted bare filenames (no path) matching the filter. Empty
            list if the category is unknown or the folder doesn't exist yet.
        """
        folder = self.SPECTRA_CATEGORY_DIRS.get(category)
        if not folder or not os.path.isdir(folder):
            return []
        
        ext_filter = (ext_filter or 'ALL').upper()
        try:
            files = os.listdir(folder)
        except Exception as e:
            logger.error(f"[SERVICE] Failed to list spectra files for category '{category}': {e}", exc_info=True)
            return []
        
        result = []
        for f in files:
            lower = f.lower()
            if ext_filter == 'JSON' and not lower.endswith('.json'):
                continue
            if ext_filter == 'SPE' and not lower.endswith('.spe'):
                continue
            if ext_filter == 'ALL' and not lower.endswith(('.json', '.spe')):
                continue
            result.append(f)
        return sorted(result)

    def build_spectra_zip(self, category: str, filenames: list):
        """Bundles the requested files from a data/spectra/ category folder into
        an in-memory .zip archive for bulk download.
        
        Args:
            category (str): One of 'background', 'batch', 'riid'.
            filenames (list): Bare filenames to include (as returned by
                list_spectra_files) - basename-only, to guard against any
                path-traversal attempt regardless of what the caller passes in.
        
        Returns:
            bytes | None: The zip archive's raw bytes, or None if the category
            is unknown, no filenames were given, or none of them existed.
        """
        folder = self.SPECTRA_CATEGORY_DIRS.get(category)
        if not folder or not filenames:
            return None
        
        buffer = io.BytesIO()
        added_any = False
        with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for name in filenames:
                safe_name = os.path.basename(str(name))
                filepath = os.path.join(folder, safe_name)
                if os.path.isfile(filepath):
                    zf.write(filepath, arcname=safe_name)
                    added_any = True
                else:
                    logger.warning(f"[SERVICE] Skipped missing file during zip export: {filepath}")
        
        if not added_any:
            return None
        buffer.seek(0)
        return buffer.getvalue()

    def delete_spectra_files(self, category: str, filenames: list) -> tuple:
        """Permanently deletes the requested files from a data/spectra/
        category folder, for the "Delete Selected" button on the Spectra
        Download tab.
        
        Args:
            category (str): One of 'background', 'batch', 'riid'.
            filenames (list): Bare filenames to delete - basename-only, same
                path-traversal guard used by build_spectra_zip.
        
        Returns:
            (bool, str): (success, message). success is True if at least one
            file was actually deleted; message summarizes the outcome,
            including any files that could not be found or removed.
        """
        folder = self.SPECTRA_CATEGORY_DIRS.get(category)
        if not folder or not filenames:
            return False, "No files selected."
        
        deleted = []
        failed = []
        for name in filenames:
            safe_name = os.path.basename(str(name))
            filepath = os.path.join(folder, safe_name)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    deleted.append(safe_name)
                else:
                    failed.append(safe_name)
            except Exception as e:
                logger.error(f"[SERVICE] Failed to delete spectra file {filepath}: {e}", exc_info=True)
                failed.append(safe_name)
        
        if deleted:
            logger.warning(f"[USER_ACTION] Operator permanently deleted {len(deleted)} spectra file(s) from category '{category}': {', '.join(deleted)}")
        
        if not deleted:
            return False, "None of the selected files could be deleted."
        if failed:
            return True, f"Deleted {len(deleted)} file(s); {len(failed)} could not be found."
        return True, f"Deleted {len(deleted)} file(s)."

    def stop_execution(self):
        """Halts the active acquisition loop without discarding the collected spectrum.
        The last spectrum trace and identification result are left exactly as they were
        so the operator can still review what was captured before pressing STOP."""
        logger.warning(f"[SERVICE] Operator pressed STOP button. Halting acquisition out of state: {self.state}")
        was_survey = self.state == 'RIID_SURVEY'
        
        self.set_state('IDLE')
        self.batch_status_text = "Halted by Operator"
        
        if was_survey:
            # Freeze the plot/ID at their last values instead of resetting to Standby.
            self.survey_stopped_with_data = bool(self.live_spectrum)
            self.status_text = "Survey Stopped - Showing Last Spectrum"
        else:
            self.status_text = "Halted by Operator"
            self.current_isotope_id = "Standby"
        
        if self._main_loop_task: self._main_loop_task.cancel()

    @property
    def is_spectrum_id_active(self) -> bool:
        """True while a Spectrum ID tab activity is in progress - either an
        active survey or a background recording (background recording is
        triggered from, and only meaningful within, the Spectrum ID tab's own
        sidebar). Used to disable the Spectrum Recording and Hardware &
        Calibration tabs while true, preventing the operator from launching a
        conflicting batch run or changing DAQ/calibration settings mid-survey
        (either of which could crash the hardware or corrupt the current
        measurement)."""
        return self.state in ('RIID_SURVEY', 'BG_RECORDING')

    @property
    def is_batch_recording_active(self) -> bool:
        """True while a Spectrum Recording (batch) run is in progress. Used to
        disable the Spectrum ID and Hardware & Calibration tabs while true,
        for the same hardware-safety reasons as is_spectrum_id_active above."""
        return self.state == 'BATCH_RECORDING'

    def clear_survey_data(self):
        """Explicitly wipes the accumulated survey spectrum trace (and its associated
        timers/state) on operator demand. This is the ONLY path that resets the live
        spectrum - starting a new survey run resumes on top of it instead (see
        start_continuous_survey), so an explicit CLEAR is required.
        Works both while idle and while a survey is actively accumulating: in the
        latter case the running acquisition loop performs the hardware-level reset
        on its next tick and keeps surveying, so STOP is not required first.
        The background spectrum profile is intentionally left untouched."""
        if self.state not in ('IDLE', 'RIID_SURVEY'):
            logger.warning(f"[SERVICE] CLEAR request rejected. Core state is busy: {self.state}")
            return
        
        logger.warning("[SERVICE] Operator pressed CLEAR button. Wiping accumulated survey spectrum (background spectrum preserved).")
        self._last_logged_detection = None
        # RESTART is the documented way out of offline analysis mode back to
        # live survey - harmless no-op if already False.
        self.offline_mode = False

        if self.state == 'RIID_SURVEY':
            # Let the active acquisition loop perform the actual hardware-level clear
            # on its own next tick rather than tearing down and rebuilding the survey.
            self.clear_requested = True
        else:
            # No survey is running, so the acquisition loop won't pick up a flag - the
            # on-board accumulator has to be cleared directly here instead. This reuses
            # the existing programmed handle; it does NOT resend any DPP parameters.
            if self.daq_device is not None and self.is_hardware_available:
                try:
                    self._call_hw(self.daq_device.open)
                    self._call_hw(self.daq_device.clear_spectrum)
                    self._call_hw(self.daq_device.timers_reset)
                    self._call_hw(self.daq_device.close)
                except Exception as e:
                    logger.error(f"[SERVICE] Hardware-level CLEAR failed: {e}", exc_info=True)
            
            self.live_spectrum = []
            self.survey_elapsed_seconds = 0
            self.survey_hardware_live_time_ms = 0.0
            self.survey_hardware_real_time_ms = 0.0
            self.survey_stopped_with_data = False
            # Pressing CLEAR is an explicit "start fresh" action, so it DOES
            # reset the count-rate history too (only the automatic
            # hysteresis-cycle reset leaves it alone - see
            # _continuous_survey_sequence's ceiling-reset branch).
            self.clear_cps_history()
            self.last_ml_result = None
            self.current_isotope_id = "Standby"
            self.status_text = "Spectrum Cleared - Ready"

    def verify_runtime_hardware_safety(self) -> bool:
        """Validates live connectivity during active data collection runs. Auto-halts on failure."""
        if not self.is_hardware_available:
            logger.critical("[ACQUISITION_GUARD] Live physical device connection lost mid-run! Intercepting crash...")
            self.set_state('IDLE')
            self.status_text = "CRITICAL: Device Disconnected Mid-Run"
            self.batch_status_text = "CRITICAL: Run aborted due to hardware loss."
            self.current_isotope_id = "Hardware Lost"
            if self._main_loop_task and not self._main_loop_task.done():
                self._main_loop_task.cancel()
            return False
        return True