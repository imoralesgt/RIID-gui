import socket
import msgpack
import threading
import time
from config import logger

class __ArduinoBridge:
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
            print(f"Connection failed: {e}")
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
                    print(f"Receive error: {e}")
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

    CHARS_SPECIAL = " +_-*/="
    CHARS_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    CHARS_NUMBERS = "0123456789"


    def __init__(self):
        self.bridge = __ArduinoBridge()
        if not self.bridge.connect():
            logger.error("Failed to connect to Arduino")
        else:
            logger.info("Connected to Arduino")

    def update_status(self, status_index : int) -> None:
        logger.info(f"Updating status in Arduino to {status_index}:{self.STATUS[status_index]}")
        self.bridge.notify("update_status", status_index)

    def __sanitize_text(self, text : str) -> str:
        sanitized_text = ''
        text = text.upper()
        for char in text:
            if char not in self.CHARS_LETTERS and char not in self.CHARS_NUMBERS and char not in self.CHARS_SPECIAL:
                sanitized_text += '_'
            else:
                sanitized_text += char
        return text

    def update_text(self, text : str) -> None:
        logger.info(f"Received text to update in Arduino: {text}")
        sanitized_text = self.__sanitize_text(text)

        if text != sanitized_text:
            logger.warning(f"Text contained invalid characters, sanitized to: {sanitized_text}")

        self.bridge.notify("update_text_matrix", sanitized_text)

def main():
    bridge = __ArduinoBridge()
    
    if not bridge.connect():
        print("Failed to connect")
        return
    
    print("Connected!")
    
    for i in range(10):
        state = i % 2 == 0
        bridge.notify("set_led_state", state)
        print(f"LED: {'ON' if state else 'OFF'}")
        time.sleep(0.5)
    
    try:
        value = bridge.call("read_temperature")
        print(f"Sensor value: {value}")
    except Exception as e:
        print(f"Error: {e}")
    
    bridge.disconnect()

if __name__ == "__main__":
    main()