import argparse
from datetime import datetime
import logging
import os
import sys
from time import sleep
from core.daq_commands import DaqCommands  # DAQ/MCA API library
import matplotlib.pyplot as plt  # Spectrum plot visualization
from tqdm import tqdm  # Dynamic progress bar tracking

# Global logger setup
logger = logging.getLogger("spectrum_recorder")


def setup_logging(verbose: bool) -> None:
    """Configures application logging for both console and file handlers.

    Logs are always written to 'spectrum_recorder.log' at the DEBUG level.
    The console logging output level is controlled dynamically by the
    verbose flag parameter to enforce strict text silence during standard runs.

    Args:
        verbose: If True, sets the console output level to DEBUG. Otherwise,
          defaults the console output level to WARNING.
    """
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )

    # File Handler (Captures everything down to DEBUG)
    file_handler = logging.FileHandler("spectrum_recorder.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Stream/Console Handler (Muted to WARNING unless verbose flag is active)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Force third-party libraries to stay quiet on the console unless debugging
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def handle_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    """Global hook to catch and log any unhandled runtime exceptions.

    Args:
        exc_type: The type of the unhandled exception.
        exc_value: The exception instance/value.
        exc_traceback: The traceback object associated with the exception.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical(
        "Uncaught exception intercepted by global hook",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


# Assign the global crash hook
sys.excepthook = handle_unhandled_exception


def get_spectrum(daq_instance: DaqCommands) -> list:
    """Collects an energy spectrum by dynamically tracking live-time timers.

    This function clears past data, resets internal hardware timers, and starts
    data acquisition. Instead of sleeping for a fixed interval, it continuously
    polls the hardware timers every second, comparing the current live-time
    (tmr_c) against the configured preset target. This ensures accurate execution
    even when high dead-time causes real-time to extend significantly.

    Args:
        daq_instance: An active instance of the DaqCommands API class.

    Returns:
        list: A list of integers representing counts per ADC channel bin.
    """
    logger.info("Initializing hardware data acquisition registers.")
    daq_instance.clear_spectrum()
    daq_instance.timers_reset()
    daq_instance.data_acquisition_start()

    initial_timers = daq_instance.timers_read()
    preset_ms = initial_timers["preset"]
    preset_seconds = int(preset_ms / 1000)

    logger.info(
        "Starting acquisition. Target Live-Time: %d seconds", preset_seconds
    )

    with tqdm(
        total=preset_seconds,
        desc="Collecting spectrum (Live-Time)"
    ) as pbar:
        last_elapsed = 0

        while True:
            timers_data = daq_instance.timers_read()
            current_live_ms = timers_data["tmr_c"]
            current_live_seconds = int(current_live_ms / 1000)

            logger.debug(
                "Polling timers -> tmr_c (live): %d ms | tmr_a (real): %d ms",
                timers_data["tmr_c"],
                timers_data["tmr_a"],
            )

            step = current_live_seconds - last_elapsed
            if step > 0:
                pbar.update(step)
                last_elapsed = current_live_seconds

            if current_live_ms >= preset_ms:
                logger.info(
                    "Target preset threshold hit inside hardware registers."
                )
                break

            sleep(1.0)

    logger.info("Target live-time reached. Fetching channel counts array.")
    spectrum = daq_instance.read_spectrum()
    return spectrum


def create_spe_file(
    file_path: str, spectrum: list, live_time: float, real_time: float, serial_number: str
) -> None:
    """Generates a standard ASCII ORTEC .Spe spectrum file.

    Args:
        file_path: Destination path or filename for the output .Spe file.
        spectrum: List of integers representing counts per ADC channel.
        live_time: Total live time of the measurement session in seconds.
        real_time: Total real time of the measurement session in seconds.
        serial_number: Hardware serial number of the detector board.
    """
    logger.info("Writing ORTEC format layout to disk path: %s", file_path)
    first_channel = 0
    last_channel = len(spectrum) - 1

    with open(file_path, "w", encoding="ascii") as f:
        f.write("$SPEC_ID:\n")
        f.write(f"NSIL-Det-{serial_number}\n")

        date_str = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        f.write("$DATE_MEA:\n")
        f.write(f"{date_str}\n")

        f.write("$MEAS_TIM:\n")
        f.write(f"{live_time:.2f} {real_time:.2f}\n")

        f.write("$DATA:\n")
        f.write(f"{first_channel} {last_channel}\n")

        for counts in spectrum:
            f.write(f"{int(counts)}\n")

        f.write("$MCA_CAL:\n3\n0.000 1.000 0.000\n")
        f.write("$ENDRECORD:\n")
    logger.debug("Successfully exported .spe file payload.")


def plot_spectrum(spectrum: list, serial_number: str, output_img: str = None) -> None:
    """Plots the energy spectrum data collected with the MCA/DAQ board.

    Args:
        spectrum: List containing the integer count data from the DAQ.
        serial_number: Hardware serial number to display on the chart title.
        output_img: File path to save the generated figure as an image. If
          omitted, an interactive GUI window will be displayed instead.
    """
    logger.info("Rendering matplotlib charts configuration styles.")
    plt.style.use("ggplot")
    plt.figure(figsize=(10, 5))
    plt.plot(range(len(spectrum)), spectrum, label="MCA Counts", linewidth=1.0)
    
    title_text = f"Captured Energy Spectrum (NaI(Tl) SiPM) - S/N: {serial_number}"
    plt.title(title_text, fontsize=12, fontweight="bold")
    
    plt.xlabel("ADC Channel Bin Number", fontsize=10)
    plt.ylabel("Event Count (N)", fontsize=10)
    plt.yscale("log")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.xlim(0, 2048)
    plt.legend(loc="upper right")

    if output_img:
        plt.savefig(output_img, dpi=300)
        logger.info("Spectrum plot successfully saved to: %s", output_img)
    else:
        logger.debug("Opening interactive matplotlib window graphical view.")
        plt.show()

def parse_arguments() -> argparse.Namespace:
    """Configures and parses command-line arguments for the application.

    Returns:
        argparse.Namespace: Object containing all parsed command-line options.
    """
    parser = argparse.ArgumentParser(
        description="Automated CLI spectrum recorder for the DAQ/MCA hardware."
    )

    # Logging and output flags
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable explicit detailed debug telemetry printouts to the console terminal",
    )

    # Application parameters (Mandatory selection)
    parser.add_argument(
        "--collection_time",
        type=int,
        required=True,
        help="Spectrum collection live-time in SECONDS",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="spectrum",
        help="Base name for the output file without extension (Default: 'spectrum')",
    )
    parser.add_argument(
        "--no_timestamp",
        action="store_true",
        help="Disable automatic date-time strings in the filename execution",
    )
    parser.add_argument(
        "--no_plot",
        action="store_true",
        help="Disable displaying the interactive graphic window upon completion",
    )
    parser.add_argument(
        "--no_save_img",
        action="store_true",
        help="Explicitly disable saving the rendered spectrum plot image to disk",
    )

    # Hardware settings
    parser.add_argument(
        "--tau_d",
        type=float,
        default=1.21e-6,
        help="Decay time of the detector signal pulse shape (s)",
    )
    parser.add_argument(
        "--tau_r",
        type=float,
        default=0.206e-6,
        help="Rise time of the detector signal pulse shape (s)",
    )
    parser.add_argument(
        "--shaper_s_tau_pk",
        type=float,
        default=2.5e-6,
        help="Peaking time of the slow pulse shaper (s)",
    )
    parser.add_argument(
        "--shaper_s_tau_pk_top",
        type=float,
        default=1.0e-6,
        help="Flat-top of the slow pulse shaper (s)",
    )
    parser.add_argument(
        "--vga_gain_coarse",
        type=float,
        default=6.0,
        help="Analog amplifier gain prior to the ADC input",
    )
    parser.add_argument(
        "--blr_s_threshold_gain",
        type=float,
        default=3.0,
        help="Baseline restorer (slow) threshold gain (baseline noise filter)",
    )
    parser.add_argument(
        "--smoothing_factor",
        type=int,
        default=2,
        help="Averaging filter smoothing factor to improve SNR. Valid values: 1, 2, 4, 8",
    )

    return parser.parse_args()


def generate_filename(output_arg: str, no_timestamp: bool) -> str:
    """Processes options to generate the final filename with an optional timestamp.

    Files are stored inside a dedicated 'spectra/' folder workspace directory
    unless absolute paths are provided.

    Args:
        output_arg: Raw filename provided via user arguments.
        no_timestamp: Flag indicating whether to skip embedding a date-time string.

    Returns:
        str: Sanitized filename path ending explicitly in '.spe' inside 'spectra/'.
    """
    target_dir = "spectra"
    os.makedirs(target_dir, exist_ok=True)

    filename = output_arg[:-4] if output_arg.endswith(".spe") else output_arg

    if not no_timestamp:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename}_{timestamp}"

    filename = f"{filename}.spe"

    if not os.path.isabs(filename):
        return os.path.join(target_dir, filename)
    return filename


def initialize_daq(args: argparse.Namespace) -> DaqCommands:
    """Instantiates the DaqCommands API wrapper using command-line arguments.

    Args:
        args: Parsed command-line arguments containing hardware configurations.

    Returns:
        DaqCommands: Prepared but unopened hardware communication instance.
    """
    preset_ms = args.collection_time * 1000
    logger.debug(
        "Initializing DaqCommands mapping parameters. Preset Time: %d ms",
        preset_ms,
    )

    return DaqCommands(
        tau_d=args.tau_d,
        tau_r=args.tau_r,
        timers_preset=preset_ms,
        timers_a_live_time=False,
        timers_c_live_time=True,
        shaper_s_tau_pk=args.shaper_s_tau_pk,
        shaper_s_tau_pk_top=args.shaper_s_tau_pk_top,
        blr_s_threshold_gain=args.blr_s_threshold_gain,
        vga_gain_coarse=args.vga_gain_coarse,
        smoothing_factor=args.smoothing_factor,
        invert_pulse=False,
    )


def run_acquisition_session(
    daq_api: DaqCommands, args: argparse.Namespace, final_filename: str
) -> None:
    """Handles the physical device runtime session workflow.

    Args:
        daq_api: Open instance of the DaqCommands hardware API.
        args: Parsed command-line argument configuration objects.
        final_filename: Target destination file path for output logging.
    """
    logger.info("Connected Device Firmware Version: %s", daq_api.get_version())
    
    serial_number = str(daq_api.get_serial())
    logger.info("Connected Device Serial Number: %s", serial_number)

    spectrum = get_spectrum(daq_api)

    timers_data = daq_api.timers_read()
    final_live = timers_data["tmr_c"] / 1000.0
    final_real = timers_data["tmr_a"] / 1000.0

    logger.info("Total Counts Collected: %d", sum(spectrum))
    logger.info(
        "Final Session Metrics -> Live-Time: %.2fs | Real-Time: %.2fs",
        final_live,
        final_real,
    )

    create_spe_file(final_filename, spectrum, final_live, final_real, serial_number)

    # Image layout generation handler
    img_path = None
    if not args.no_save_img:
        # Replaces .spe extension with .png automatically to match the exact dataset name
        img_path = final_filename[:-4] + ".png"

    if img_path or not args.no_plot:
        plot_spectrum(
            spectrum, serial_number=serial_number, output_img=img_path
        )


def main():
    """Main execution orchestrator for the automated spectrum recorder application."""
    args = parse_arguments()

    setup_logging(args.verbose)
    logger.debug("System logging channels successfully configured.")

    final_filename = generate_filename(args.output, args.no_timestamp)
    daq_api = initialize_daq(args)

    try:
        logger.info("Opening communication channel link via serial connection.")
        daq_api.open()
        run_acquisition_session(daq_api, args, final_filename)
    except Exception as e:
        logger.error(
            "Acquisition failed due to physical hardware error.", exc_info=True
        )
    finally:
        logger.info("Closing down hardware communication channels safely.")
        daq_api.close()
        logger.info("Session sequence complete.")


if __name__ == "__main__":
    main()
