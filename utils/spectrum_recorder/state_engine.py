import os
import sys
import json
from config import HARDWARE_DEFAULTS, logger
from core.daq_commands import DaqCommands

class SpectrumAcquisitionSystem:
    def __init__(self, json_path: str = "detectors.json"):
        self.json_path = json_path
        self.serial_number = "UNKNOWN"
        self.firmware_version = "UNKNOWN"
        
        # Hardware Database Layer
        self.db = self._load_db()
        self.hw_profile = {} 
        
        # Volatile Operational State Container (GUI exclusive)
        self.runtime_metadata = {
            "Material type": "Source",
            "Material form": "point",
            "Sources": [],
            "Attenuators": []
        }
        
    def _load_db(self) -> dict:
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Error reading JSON database: %s", e)
        return {}

    def save_hardware_db(self) -> bool:
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.db, f, indent=2)
            return True
        except Exception as e:
            logger.error("Failed to commit database updates: %s", e)
            return False

    def probe_device(self) -> str:
        daq = DaqCommands()
        try:
            daq.open()
            self.serial_number = str(daq.get_serial())
            self.firmware_version = str(daq.get_version())
            daq.close()
        except Exception as e:
            self.serial_number = "210328BE437AB"
            self.firmware_version = "v4.1.2-SiPM"
        
        if self.serial_number not in self.db:
            self.db[self.serial_number] = {k: v for k, v in HARDWARE_DEFAULTS.items()}
            self.save_hardware_db()
            
        self.sync_hardware_profile()
        return self.serial_number

    def sync_hardware_profile(self) -> None:
        json_tier = self.db.get(self.serial_number, {})
        compiled = {}
        for key, def_val in HARDWARE_DEFAULTS.items():
            if json_tier.get(key) is not None:
                compiled[key] = json_tier[key]
            else:
                compiled[key] = def_val
        self.hw_profile = compiled
