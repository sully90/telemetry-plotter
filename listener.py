import socket
import struct
import threading
from PyQt5 import QtCore

# F1 25 Packet Header (29 bytes)
HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Packet IDs
PACKET_ID_SESSION = 1
PACKET_ID_LAP_DATA = 2
PACKET_ID_CAR_TELEMETRY = 6

class TelemetryListener(QtCore.QObject):
    """UDP listener for raw F1 25 packets."""
    track_received = QtCore.pyqtSignal(int)
    lap_received = QtCore.pyqtSignal(int, float, int) # lap_num, distance, time_ms
    telemetry_received = QtCore.pyqtSignal(float, int, float, float) # speed, rpm, throttle, brake
    
    def __init__(self, port):
        super().__init__()
        self.port = port
        self._running = True

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', self.port))
        sock.settimeout(1.0)
        print(f"Listening for RAW F1 25 telemetry on port {self.port}...")

        while self._running:
            try:
                data, addr = sock.recvfrom(2048)
                if len(data) < HEADER_SIZE:
                    continue

                header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
                packet_id = header[5]
                player_idx = header[10] # Correct index for m_playerCarIndex

                if packet_id == PACKET_ID_SESSION:
                    # m_trackId is at offset 29 + 1 + 1 + 1 + 1 + 2 + 1 = 36
                    if len(data) >= 37:
                        track_id = struct.unpack("<b", data[36:37])[0]
                        self.track_received.emit(track_id)

                if packet_id == PACKET_ID_LAP_DATA:
                    # LapData entry is 57 bytes in F1 25
                    entry_size = 57 
                    offset = HEADER_SIZE + (player_idx * entry_size)
                    if len(data) >= offset + 57:
                        # m_lapDistance: float at offset + 20
                        # m_currentLapNum: uint8 at offset + 33
                        # m_currentLapTimeInMS: uint32 at offset + 4
                        time_ms = struct.unpack("<I", data[offset+4:offset+8])[0]
                        dist = struct.unpack("<f", data[offset+20:offset+24])[0]
                        lap = struct.unpack("<B", data[offset+33:offset+34])[0]
                        self.lap_received.emit(lap, dist, time_ms)


                elif packet_id == PACKET_ID_CAR_TELEMETRY:
                    # CarTelemetry entry is 60 bytes in F1 25
                    entry_size = 60
                    offset = HEADER_SIZE + (player_idx * entry_size)
                    if len(data) >= offset + 60:
                        # speed (uint16) at +0, throttle (float) at +2, brake (float) at +10, rpm (uint16) at +16
                        speed = struct.unpack("<H", data[offset:offset+2])[0]
                        throttle = struct.unpack("<f", data[offset+2:offset+6])[0]
                        brake = struct.unpack("<f", data[offset+10:offset+14])[0]
                        rpm = struct.unpack("<H", data[offset+16:offset+18])[0]
                        self.telemetry_received.emit(float(speed), int(rpm), throttle, brake)

            except socket.timeout:
                continue
            except Exception as e:
                # print(f"UDP Decode Error: {e}")
                pass

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._running = False
