from core.daq_hw import DaqHw
from core.dpp_parameters import DppParameters

class DaqCommands:
    def __init__(self, daq_port_instance : DaqHw):
        self.daq = daq_port_instance
    
