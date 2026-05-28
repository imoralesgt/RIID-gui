from serial import Serial
from serial.tools import list_ports
import os

class DaqHw(Serial):

    #: Use these default values for the USB-UART FTDI chip in the CMOD A7 board
    DEFAULT_VID = "0403"
    DEFAULT_PID = "6010"

    def _disregard_jtag(self):
        """
        Returns a list of UART-only ports associated to /dev/ttyUSB or /dev/ttyACM interfaces.
        Disregards any JTAG channel available in a single USB-UART FTDI chip.

        Returns
        -------
        list
            A list of UART-only ports
        """
        
        base_path = "/dev/serial/by-id/"
        uart_ports = []

        # Validate the working directory exists
        if not os.path.exists(base_path):
            return uart_ports

        # Seek in the directory for the available serial ports
        for filename in os.listdir(base_path):
            # Filter out everything besides the if01 (UART)
            if "if01" in filename:
                full_path = os.path.join(base_path, filename)

                # Solve the symbolic link (for example. ../../ttyUSB1 -> /dev/ttyUSB1)
                real_path = os.path.realpath(full_path)
                uart_ports.append(real_path)

        # Returns a list of UART-only ports associated to /dev/ttyUSB or /dev/ttyACM... 
        return sorted(uart_ports)


    def find_port(self, vid : int, pid : int) -> str:
        """
        Finds the serial port of the target device. If unsure of
        the VID and PID, use the DEFAULT_VID and DEFAULT_PID class attributes.

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

        # All the COM ports, including JTAG instances
        ports = list_ports.comports()
        
        # Valid UART ports, no matter VID, PID
        valid_uart_ports = self._disregard_jtag()

        devices = []

        # Scan the available ports, looking for the target device
        for port in ports:
            if port.vid == target_vid and port.pid == target_pid:
                device_name = port.device
                
                #Only if UART (serial port) instance, disregard JTAG
                if device_name in valid_uart_ports: 
                    devices.append(device_name)

        if len(devices) == 1:
            return devices[0]
        elif len(devices) > 1:
            return devices               

        return None
    
    def open_port(self, port_name : str, baudrate : int) -> Serial:
        """
        Opens a serial port

        Parameters
        ----------
        port_name : str
            The serial port to open
        baudrate : int
            The baudrate of the serial port

        Returns
        -------
        Serial
            The instance of the opened serial port
        """
        return super().__init__(port_name, baudrate)
    
    def close_port(self, port_instance : Serial) -> bool:
        """
        Closes a serial port

        Parameters
        ----------
        port_instance : Serial
            The instance of the serial port to close

        Returns
        -------
        bool
            True if the port was closed succesfully. False if it was already closed
        """
        if port_instance.is_open:
            port_instance.close()
            return True
        return False

if __name__ == "__main__":

    ## This is a validation code that should not be run in production
    daq = DaqHw()

    ## Taking the default VID and PID for the CMOD A7 development board
    vid = daq.DEFAULT_VID
    pid = daq.DEFAULT_PID

    ## Finding the port corresponding to the device we are looking for
    port_name = daq.find_port(vid, pid)
    print(f"DAQ found in port: {port_name}")

    ## Checking if the port can be opened and closed
    daq.open_port(port_name, 115200)
    print(f"Port opened: {daq.is_open}")
    daq.close_port(daq)
    print(f"Port closed: {not daq.is_open}")
