import socket
import msgpack
import threading
import time
from config import logger

class _ArduinoBridge:
    def __init__(self, socket_path="/var/run/arduino-router.sock"):
        self.socket_path = socket_path
        self.sock = None
        self.msg_counter = 0
        self.pending_responses = {}
        self.running = False
        self.recv_thread = None
        self.lock = threading.Lock()
        
    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.socket_path)
            
            self.running = True
            self.recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.recv_thread.start()
            
            return True
        except Exception as e:
            logger.error(f"Bridge could not be initialized. Connection failed: {e}")
            return False
    
    def call(self, method, *args, timeout=5):
        self.msg_counter += 1
        msgid = self.msg_counter
        
        message = [0, msgid, method, list(args)]
        packed = msgpack.packb(message)
        
        event = threading.Event()
        with self.lock:
            self.pending_responses[msgid] = {"event": event, "result": None, "error": None}
        
        self.sock.sendall(packed)
        
        if event.wait(timeout):
            with self.lock:
                response = self.pending_responses.pop(msgid)
            
            if response["error"]:
                raise Exception(response["error"])
            return response["result"]
        else:
            with self.lock:
                self.pending_responses.pop(msgid, None)
            raise TimeoutError(f"Timeout waiting for {method}")
    
    def notify(self, method, *args):
        message = [2, method, list(args)]
        packed = msgpack.packb(message)
        self.sock.sendall(packed)
    
    def disconnect(self):
        self.running = False
        if self.sock:
            self.sock.close()
        if self.recv_thread:
            self.recv_thread.join(timeout=1)
    
    def _receive_loop(self):
        unpacker = msgpack.Unpacker()
        while self.running:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                
                unpacker.feed(data)
                for msg in unpacker:
                    self._handle_response(msg)
            except Exception as e:
                if self.running:
                    logger.error(f"Receive error: {e}")
                break
    
    def _handle_response(self, msg):
        if not isinstance(msg, list) or len(msg) < 4:
            return
        
        msg_type, msgid, error, result = msg[0], msg[1], msg[2], msg[3]
        
        if msg_type != 1:
            return
        
        with self.lock:
            if msgid in self.pending_responses:
                self.pending_responses[msgid]["error"] = error
                self.pending_responses[msgid]["result"] = result
                self.pending_responses[msgid]["event"].set()

class ArduinoInterface:

    STATUS = {
        0: "IDLE",
        1: "BKGND_REC",
        2: "SURVEY_NO_RIID",
        3: "SURVEY_RIID_OK"
    }

    CHARS_SPECIAL = " +_-*/=."
    CHARS_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    CHARS_NUMBERS = "0123456789"

    RPC_UPDATE_STATUS_FUNC = "update_status_led"
    RPC_UPDATE_TEXT_FUNC = "update_text_matrix"


    def __init__(self):
        self.bridge = _ArduinoBridge()
        if not self.bridge.connect():
            logger.error("Failed to connect to Arduino RPC router service.")
            raise Exception("Failed to connect to Arduino RPC router service.")
        else:
            logger.info("Connected to Arduino")

    def disconnect(self):
        """Gracefully disconnects from the Arduino RPC router.
        """
        logger.info("Gracefully disconnecting from the Arduino RPC router...")
        self.bridge.disconnect()

    def update_status(self, status_index : int) -> None:
        """Updates the status shown in the onboard RGB LED of the Arduino Q board.
        Leverages the existing RPC router instance initialized in the class constructor.

        The `STATUS` class property is used to map the status index to a human-readable logged string.
        The sent value is a simple int-8 value, though.

        Args:
            status_index (int): The index of the status to be displayed

        Returns:
            None
        """
        logger.info(f"Updating status in Arduino to {status_index}:{self.STATUS[status_index]}")
        self.bridge.notify(self.RPC_UPDATE_STATUS_FUNC, status_index)

    def __sanitize_text(self, text : str) -> str:
        """Sanitizes the provided string by removing non-existing characters.
        Used to prevent the LED matrix from displaying invalid characters.
        
        Args:
            text (str): The text to be sanitized

        Returns:
            str: The sanitized text
        """

        FALLBACK_CHAR = '_'
        sanitized_text = ''

        text = text.upper()
        for char in text:
            if (char not in self.CHARS_LETTERS) and (char not in self.CHARS_SPECIAL) and (char not in self.CHARS_NUMBERS):
                sanitized_text += FALLBACK_CHAR
            else:
                sanitized_text += char

        if text != sanitized_text:
            logger.warning(f"Text contained invalid characters, sanitized to: {sanitized_text}")

        return text

    def update_text(self, text : str) -> None:
        """Updates the text shown in the LED matrix of the Arduino Q board.
        Sanitizes the string by removing non-existing characters. Leverages
        the existing RPC router instance initialized in the class constructor.

        Args:
            text (str): The text to be displayed on the LED matrix

        Returns:
            None
        """
        logger.info(f"Received text to update in Arduino: {text}")
        sanitized_text = self.__sanitize_text(text)
        self.bridge.notify(self.RPC_UPDATE_TEXT_FUNC, sanitized_text)

    def update_scroll_speed(self, speed : int) -> None:
        """Updates the scroll speed shown in the LED matrix of the Arduino Q board.
        Leverages the existing RPC router instance initialized in the class constructor.

        Args:
            speed (int): The scroll speed to be displayed on the LED matrix

        Returns:
            None
        """
        logger.info(f"Received scroll speed to update in MCU LED matrix display: {speed}")
        self.bridge.notify("update_scroll_speed", speed)

    def clear_text(self):
        self.update_text("")

def main():
    arduino_if = ArduinoInterface()

    for i in range(10):
        arduino_if.update_status(list(arduino_if.STATUS.keys())[0])
        arduino_if.update_text("HELLO WORLD+TEST_&!INVALID CHAR")
        arduino_if.update_scroll_speed(60);
        time.sleep(15)

        arduino_if.update_status(list(arduino_if.STATUS.keys())[1])
        arduino_if.update_text("Short text, no special chars")
        arduino_if.update_scroll_speed(200);
        time.sleep(15)

        arduino_if.update_status(list(arduino_if.STATUS.keys())[2])
        arduino_if.update_text("Status - no RIID")
        arduino_if.update_scroll_speed(40);
        time.sleep(15)

        arduino_if.update_status(list(arduino_if.STATUS.keys())[3])
        arduino_if.clear_text()
        time.sleep(15)
    
    arduino_if.disconnect()


if __name__ == "__main__":
    main()