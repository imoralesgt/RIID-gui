import argparse
from datetime import datetime
import json
import logging
import os
import sys
from time import sleep
from core.daq_commands import DaqCommands  # DAQ/MCA API library
import matplotlib.pyplot as plt  # Spectrum plot visualization
from tqdm import tqdm  # Dynamic progress bar tracking

# Global logger setup
logger = logging.getLogger("spectrum_recorder")


class ConfigurationManager:
    """Handles parsing CLI arguments, loading/updating JSON profiles, and parameter fallbacks."""

    # Script fallback defaults as defined by specification
    DEFAULTS_DPP = {
        "tau_d": 1.21e-6,
        "tau_r": 0.206e-6,
        "shaper_s_tau_pk": 2.5e-6,
        "shaper_s_tau_pk_top": 1.0e-6,
        "vga_gain_coarse": 6.0,
        "blr_s_threshold_gain": 3.0,
        "smoothing_factor": 2,
        "invert_pulse": False,
        "calib_a0": 0.0,
        "calib_a1": 1.0,
        "calib_a2": 2.0,
    }

    OUTPUT_FOLDER = "spectra"

    def __init__(self):
        """Initializes the ConfigurationManager and parses runtime CLI options."""
        self.args = self._parse_arguments()

    def _parse_arguments(self) -> argparse.Namespace:
        """Configures and parses command-line arguments for the application.

        Returns:
            argparse.Namespace: Object containing all parsed command-line options.
        """
        parser = argparse.ArgumentParser(
            description="Automated CLI spectrum recorder for the DAQ/MCA hardware."
        )

        # Logging and output flags
        parser.add_argument(
            "--verbose", action="store_true",
            help="Enable explicit detailed debug telemetry printouts to the console terminal",
        )

        # Application parameters (Mandatory selection)
        parser.add_argument(
            "--collection_time", type=int, default=300,
            help="Spectrum collection live-time in SECONDS",
        )
        parser.add_argument(
            "--output", type=str, default="spectrum",
            help="Base name for the output file without extension (Default: 'spectrum')",
        )
        parser.add_argument(
            "-n", "--spectra_count", type=int, default=1, dest="spectra_count",
            help="Number of sequential spectra (N) to record automatically (Default: 1)",
        )
        parser.add_argument(
            "--no_timestamp", action="store_true",
            help="Disable automatic date-time strings in the filename execution",
        )
        parser.add_argument(
            "--show_plot", action="store_true",
            help="Enable displaying the interactive graphic window upon completion (Disabled by default)",
        )
        parser.add_argument(
            "--no_save_img", action="store_true",
            help="Explicitly disable saving the rendered spectrum plot image to disk",
        )

        # Hardware tuning options
        parser.add_argument("--tau_d", type=float, default=None, help="Decay time shape (s)")
        parser.add_argument("--tau_r", type=float, default=None, help="Rise time shape (s)")
        parser.add_argument("--shaper_s_tau_pk", type=float, default=None, help="Peaking time slow shaper (s)")
        parser.add_argument("--shaper_s_tau_pk_top", type=float, default=None, help="Flat-top slow shaper (s)")
        parser.add_argument("--vga_gain_coarse", type=float, default=None, help="Analog coarse gain before ADC")
        parser.add_argument("--blr_s_threshold_gain", type=float, default=None, help="BLR threshold gain filter")
        parser.add_argument("--smoothing_factor", type=int, default=None, help="SNR moving average filter")
        
        # Calibration options
        parser.add_argument("--calib_a0", type=float, default=None, help="Calibration coefficient a0 (Offset)")
        parser.add_argument("--calib_a1", type=float, default=None, help="Calibration coefficient a1 (Linear)")
        parser.add_argument("--calib_a2", type=float, default=None, help="Calibration coefficient a2 (Quadratic)")

        return parser.parse_args()

    def setup_logging(self) -> None:
        """Configures dual-pipe system logging outputs for files and terminal streams."""
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
        )

        file_handler = logging.FileHandler("spectrum_recorder.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if self.args.verbose else logging.WARNING)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        logging.getLogger("matplotlib").setLevel(logging.WARNING)

    def load_json_profile(self, serial_number: str, json_path: str = "detectors.json") -> dict:
        """Loads calibration overrides matching a specific serial number parent key from JSON."""
        data = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error("Failed to parse configuration database '%s': %s", json_path, e)
                data = {}

        if serial_number in data:
            logger.info("Matching profile found in JSON for S/N: %s", serial_number)
            return data[serial_number]

        logger.warning(
            "S/N: %s not found in '%s'. Registering new device profile entry with default parameters.",
            serial_number, json_path
        )
        data[serial_number] = self.DEFAULTS_DPP.copy()
        
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("Successfully registered default profile mapping database entries for S/N: %s", serial_number)
        except Exception as e:
            logger.error("Failed to append new device profile updates to configuration file '%s': %s", json_path, e)

        return data[serial_number]

    def resolve_parameters(self, profile: dict) -> dict:
        """Resolves digital pulse processing values using a strict 3-tier hierarchy matrix."""
        resolved = {}
        for key, script_default in self.DEFAULTS_DPP.items():
            cli_value = getattr(self.args, key, None)
            
            if cli_value is not None:
                resolved[key] = cli_value
                logger.debug("Parameter '%s' resolved via Tier 1 [CLI]: %s", key, cli_value)
            elif key in profile:
                resolved[key] = profile[key]
                logger.debug("Parameter '%s' resolved via Tier 2 [JSON Profile]: %s", key, profile[key])
            else:
                resolved[key] = script_default
                logger.debug("Parameter '%s' resolved via Tier 3 [Script Default]: %s", key, script_default)
                
        return resolved
    
    def __remove_ext_filename(self, filename : str) -> str:
        """Removes the file extension from a filename, if present.
        
        Args:
            filename (str): Input filename.

        Returns:
            str: Filename without extension
        """
        if "." in filename:
            filename = filename.split('.')[0]
        
        return filename

    def generate_filename(self, serial_number: str, timestamp_str: str, loop_index: int = None) -> str:
        """Processes parameters to calculate file save destinations inside the output folder.
        
        Args:
            serial_number (str): Device serial number.
            timestamp_str (str): Timestamp string for the current session.
            loop_index (int, optional): Sequential run index.

        Returns:
            str: Generated filename
        """
        target_dir = self.OUTPUT_FOLDER
        os.makedirs(target_dir, exist_ok=True)

        if not self.args.no_timestamp:
            filename = f"{timestamp_str}_{serial_number}"
        else:
            filename = serial_number
      
        base_name = self.__remove_ext_filename(self.args.output)      
        filename = f"{filename}_{base_name}"
        
        if loop_index is not None:
            filename = f"{filename}_run{loop_index:02d}"

        if not os.path.isabs(filename):
            return os.path.join(target_dir, filename)
        return filename

class SpectrumRecorderApp:
    """Manages the physical hardware connections, measurements, and data generation."""

    def __init__(self, config_mgr: ConfigurationManager):
        """Initializes the application using an active configuration instance."""
        self.config_mgr = config_mgr
        self.serial_number = "UNKNOWN"
        self.firmware_version = "UNKNOWN"

    def probe_hardware_identity(self) -> str:
        """Opens a quick baseline channel to query device identification markers."""
        logger.info("Probing device to resolve hardware identity signature...")
        probe_daq = DaqCommands()
        try:
            probe_daq.open()
            self.serial_number = str(probe_daq.get_serial())
            self.firmware_version = str(probe_daq.get_version())
            probe_daq.close()
            return self.serial_number
        except Exception as e:
            logger.error("Failed to extract device signature info during initial probe phase: %s", e)
            sys.exit(1)

    def run_acquisition(self, dpp_settings: dict) -> None:
        """Initializes final device settings and loops continuous acquisition counters.

        Args:
            dpp_settings: Resolved hardware configuration settings parameter dictionary.
        """
        preset_ms = self.config_mgr.args.collection_time * 1000
        total_runs = self.config_mgr.args.spectra_count

        if not self.config_mgr.args.show_plot:
            plt.switch_backend('Agg')
            logger.debug("Headless rendering context activated via matplotlib 'Agg' backend engine.")

        session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        daq_api = DaqCommands(
            timers_preset=preset_ms,
            timers_a_live_time=False,
            timers_c_live_time=True,
            invert_pulse=dpp_settings["invert_pulse"],
            tau_d=dpp_settings["tau_d"],
            tau_r=dpp_settings["tau_r"],
            shaper_s_tau_pk=dpp_settings["shaper_s_tau_pk"],
            shaper_s_tau_pk_top=dpp_settings["shaper_s_tau_pk_top"],
            vga_gain_coarse=dpp_settings["vga_gain_coarse"],
            blr_s_threshold_gain=dpp_settings["blr_s_threshold_gain"],
            smoothing_factor=dpp_settings["smoothing_factor"]
        )

        try:
            logger.info("Opening production communication channel link via serial connection.")
            daq_api.open()
            logger.info("Connected Device Firmware Version: %s", self.firmware_version)
            logger.info("Connected Device Serial Number: %s", self.serial_number)

            for run_idx in range(1, total_runs + 1):
                if total_runs > 1:
                    print(f"\n--- Starting Spectrum Acquisition Cycle [{run_idx}/{total_runs}] ---")
                    logger.info("Executing continuous sequence batch tracking cycle %d/%d", run_idx, total_runs)

                daq_api.clear_spectrum()
                daq_api.timers_reset()
                daq_api.data_acquisition_start()

                print(f"Acquisition running. Target Live-Time: {self.config_mgr.args.collection_time} seconds")

                with tqdm(total=self.config_mgr.args.collection_time, desc=f"Collecting spectrum #{run_idx}") as pbar:
                    last_elapsed = 0
                    while True:
                        timers_data = daq_api.timers_read()
                        current_live_ms = timers_data["tmr_c"]
                        current_live_seconds = int(current_live_ms / 1000)

                        logger.debug("Polling timers -> tmr_c: %d ms | tmr_a: %d ms", current_live_ms, timers_data["tmr_a"])

                        step = current_live_seconds - last_elapsed
                        if step > 0:
                            pbar.update(step)
                            last_elapsed = current_live_seconds

                        if current_live_ms >= preset_ms:
                            break
                        sleep(1.0)

                spectrum = daq_api.read_spectrum()
                timers_final = daq_api.timers_read()
                
                loop_param = run_idx if total_runs > 1 else None
                self._save_session_outputs(spectrum, timers_final, session_timestamp, dpp_settings, loop_index=loop_param)

        except Exception as e:
            logger.error("Acquisition failed due to physical hardware error.", exc_info=True)
        finally:
            daq_api.close()
            logger.info("Serial communication interface channel closed safely.")

    def _save_session_outputs(self, spectrum: list, timers_final: dict, session_timestamp: str, dpp_settings: dict, loop_index: int = None) -> None:
        """Internal worker logic managing file export and plotting executions."""
        final_live = timers_final["tmr_c"] / 1000.0
        final_real = timers_final["tmr_a"] / 1000.0
        final_filename = self.config_mgr.generate_filename(self.serial_number, session_timestamp, loop_index=loop_index)

        logger.info("Total Counts Collected: %d", sum(spectrum))
        logger.info("Metrics -> Live-Time: %.2fs | Real-Time: %.2fs", final_live, final_real)

        # Enviar el diccionario de configuraciones resueltas para inyectar los coeficientes
        self._export_spe_file(f"{final_filename}.spe", spectrum, final_live, final_real, dpp_settings)

        img_path = final_filename + ".png" if not self.config_mgr.args.no_save_img else None
        if img_path or self.config_mgr.args.show_plot:
            self._render_plot(spectrum, img_path)

    def _export_spe_file(self, path: str, spectrum: list, live: float, real: float, dpp_settings: dict) -> None:
        """Generates standard ASCII ORTEC format dataset output entries."""
        logger.info("Writing ORTEC dataset to path: %s", path)
        with open(path, "w", encoding="ascii") as f:
            f.write(f"$SPEC_ID:\nNSIL-Det-{self.serial_number}\n")
            f.write(f"$DATE_MEA:\n{datetime.now().strftime('%m/%d/%Y %H:%M:%S')}\n")
            f.write(f"$MEAS_TIM:\n{live:.2f} {real:.2f}\n")
            f.write(f"$DATA:\n0 {len(spectrum) - 1}\n")
            for counts in spectrum:
                f.write(f"{int(counts)}\n")
            
            # Almacenar de forma dinámica los coeficientes de calibración resueltos por la jerarquía de 3 niveles
            f.write("$MCA_CAL:\n3\n")
            f.write(f"{dpp_settings['calib_a0']:.7e} {dpp_settings['calib_a1']:.7e} {dpp_settings['calib_a2']:.7e}\n")
            
            f.write("$ENDRECORD:\n")

    def _render_plot(self, spectrum: list, img_path: str = None) -> None:
        """Builds configuration templates and draws spectrum charts."""
        plt.style.use("ggplot")
        plt.figure(figsize=(10, 5))
        plt.plot(range(len(spectrum)), spectrum, label="MCA Counts", linewidth=1.0)
        plt.title(f"Captured Energy Spectrum - S/N: {self.serial_number}", fontsize=12, fontweight="bold")
        plt.xlabel("ADC Channel Bin Number", fontsize=10)
        plt.ylabel("Event Count (N)", fontsize=10)
        plt.yscale("log")
        plt.grid(True, linestyle="--", alpha=0.6)
        plt.xlim(0, 2048)
        plt.legend(loc="upper right")

        if img_path:
            plt.savefig(img_path, dpi=300)
            logger.info("Spectrum chart successfully exported to: %s", img_path)
        if self.config_mgr.args.show_plot:
            plt.show()
        plt.close()


def handle_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    """Global hook interceptor targeting clean logs mapping for unhandled errors."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Critical unhandled runtime error intercepted:", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_unhandled_exception


def main():
    """Main application launcher initializing object orchestration workflows.
    
    This execution lifecycle follows a strict pipeline:
      1. Instantiates a ConfigurationManager to catch and sanitize user console input.
      2. Set up background logs tracing and standard terminal streams handlers.
      3. Probes the hardware serial port via a temporary lightweight connection to pull the serial number.
      4. References the pulled serial number against 'detectors.json' to query DPP parameters.
      5. Runs the 3-Tier matrix resolving engine (CLI beats JSON Profile, which beats Defaults).
      6. Runs up a permanent hardware link session and loops acquisition N sequential times.
    """
    config_mgr = ConfigurationManager()
    config_mgr.setup_logging()

    app = SpectrumRecorderApp(config_mgr)
    serial_number = app.probe_hardware_identity()
    
    profile = config_mgr.load_json_profile(serial_number)
    dpp_settings = config_mgr.resolve_parameters(profile)

    app.run_acquisition(dpp_settings)


if __name__ == "__main__":
    main()

