from serial import Serial, tools

class DaqHw:
    def __init__(self, baudrate : int = 115200):
        pass

    def find_port(self, vid : int, pid : int) -> str:
        """
        Finds the serial port of the target device

        Parameters
        ----------
        vid : int
            The vendor ID of the target device
        pid : int
            The product ID of the target device

        Returns
        -------
        str
            The serial port of the target device
        """
        
        # Convert to integers in case hexadecimal text is passed as parameter
        target_vid = int(vid, 16) if isinstance(vid, str) else vid
        target_pid = int(pid, 16) if isinstance(pid, str) else pid

        ports = tools.list_ports.comports()

        # Scan the available ports, looking for the target device
        for port in ports:
            if port.vid == target_vid and port.pid == target_pid:
                return port.device

        return None
    
    def open_port(self, port_name : str, baudrate : int):
        return Serial(port_name, baudrate)
    
    def close_port(self, port_instance : Serial):
        port_instance.close()

if __name__ == "__main__":
    VID = "0403"
    PID = "6010"

    daq = DaqHw()
    port_name = daq.find_port(VID, PID)
    print(port_name)
