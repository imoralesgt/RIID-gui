import os
import sys
import json
from config import HARDWARE_DEFAULTS, DETECTORS_DB_PATH, SOURCES_DB_PATH, logger
from core.daq_commands import DaqCommands

class SpectrumAcquisitionSystem:
    def __init__(self, json_path: str = DETECTORS_DB_PATH, sources_path: str = SOURCES_DB_PATH):
        self.json_path = json_path
        self.sources_path = sources_path
        self.serial_number = "UNKNOWN"
        self.firmware_version = "UNKNOWN"
        
        # Hardware & Source Databases
        self.db = self._load_json(self.json_path)
        self.sources_db = self._load_json(self.sources_path)
        self.hw_profile = {} 
        
        # Volatile Operational State Container (GUI exclusive)
        self.runtime_metadata = {
            "Material type": "Source",
            "Material form": "point",
            "Sources": [],
            "Attenuators": []
        }
        
    def _load_json(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Error reading JSON database %s: %s", path, e)
        return {}

    def save_hardware_db(self) -> bool:
        try:
            # Dynamically resolve target directory path using constant configuration
            os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.db, f, indent=2)
            return True
        except Exception as e:
            logger.error("Failed to commit database updates: %s", e)
            return False

    def save_sources_db(self) -> bool:
        try:
            # Dynamically resolve target directory path using constant configuration
            os.makedirs(os.path.dirname(self.sources_path), exist_ok=True)
            with open(self.sources_path, "w", encoding="utf-8") as f:
                json.dump(self.sources_db, f, indent=2)
            return True
        except Exception as e:
            logger.error("Failed to commit sources database updates: %s", e)
            return False

    def probe_device(self) -> str:
        daq = DaqCommands()
        try:
            daq.open()
            self.serial_number = str(daq.get_serial())
            self.firmware_version = str(daq.get_version())
            daq.close()
        except Exception as e:
            raise Exception(f"Hardware not found: {e}")
        
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
