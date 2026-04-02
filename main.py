import sys
import struct
import socket
import threading
import argparse
from collections import deque
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

# Configuration
DEFAULT_UDP_PORT = 20778

# F1 25 Packet Header (29 bytes)
HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Packet IDs
PACKET_ID_SESSION = 1
PACKET_ID_LAP_DATA = 2
PACKET_ID_CAR_TELEMETRY = 6

TRACK_MAP = {
    0: "Melbourne", 1: "Paul Ricard", 2: "Shanghai", 3: "Sakhir",
    4: "Catalunya", 5: "Monaco", 6: "Montreal", 7: "Silverstone",
    8: "Hockenheim", 9: "Hungaroring", 10: "Spa", 11: "Monza",
    12: "Singapore", 13: "Suzuka", 14: "Abu Dhabi", 15: "Texas",
    16: "Shanghai", 17: "Interlagos", 18: "Yas Marina", 19: "Austin",
    20: "Mexico City", 21: "Spielberg", 22: "Sakhir Short", 
    23: "Silverstone Short", 24: "Texas Short", 25: "Suzuka Short",
    26: "Hanoi", 27: "Zandvoort", 28: "Imola", 29: "Portimão",
    30: "Jeddah", 31: "Miami", 32: "Las Vegas", 33: "Losail"
}

class TelemetryData:
    """Manages telemetry data for multiple laps."""
    def __init__(self, max_laps=5):
        self.max_laps = max_laps
        self.laps = deque(maxlen=max_laps)
        self.current_lap_data = self._new_lap_dict()
        self.best_lap_data = None
        self.best_lap_time = float('inf')
        self.current_lap_num = -1
        self.lock = threading.Lock()
        self.track_name = "F1 25 Session"
        self.first_data_received = False

    def _new_lap_dict(self):
        return {
            "distance": [],
            "speed": [],
            "rpm": [],
            "throttle": [],
            "brake": [],
            "time": []
        }

    def update_lap(self, lap_num, distance, time_ms):
        if not self.first_data_received:
            print(f"Successfully receiving F1 25 binary telemetry!")
            self.first_data_received = True
            
        with self.lock:
            # Detect new lap
            if self.current_lap_num != -1 and lap_num > self.current_lap_num:
                lap_time = self.current_lap_data["time"][-1] if self.current_lap_data["time"] else float('inf')
                
                # Check if this was the best lap
                if len(self.current_lap_data["distance"]) > 100:
                    if lap_time < self.best_lap_time:
                        self.best_lap_time = lap_time
                        self.best_lap_data = self.current_lap_data
                    
                    self.laps.append(self.current_lap_data)
                
                self.current_lap_data = self._new_lap_dict()
            
            # Detect session reset
            if lap_num < self.current_lap_num and lap_num != -1:
                self.laps.clear()
                self.best_lap_data = None
                self.best_lap_time = float('inf')
                self.current_lap_data = self._new_lap_dict()

            self.current_lap_num = lap_num
            self.current_lap_data["distance"].append(distance)
            self.current_lap_data["time"].append(time_ms / 1000.0)

    def update_track(self, track_id):
        with self.lock:
            new_track = TRACK_MAP.get(track_id, f"Track {track_id}")
            if new_track != self.track_name:
                self.track_name = new_track
                self.laps.clear()
                self.best_lap_data = None
                self.best_lap_time = float('inf')
                self.current_lap_data = self._new_lap_dict()

    def update_telemetry(self, speed, rpm, throttle, brake):
        with self.lock:
            if len(self.current_lap_data["distance"]) > len(self.current_lap_data["speed"]):
                self.current_lap_data["speed"].append(speed)
                self.current_lap_data["rpm"].append(rpm)
                self.current_lap_data["throttle"].append(throttle * 100.0)
                self.current_lap_data["brake"].append(brake * 100.0)

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

class PlotterWindow(QtWidgets.QMainWindow):
    def __init__(self, telemetry_data):
        super().__init__()
        self.telemetry_data = telemetry_data
        self.setWindowTitle("SimHub Real-Time Telemetry Plotter")
        self.resize(1000, 800)

        # UI Setup
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)

        # pg Graphics Layout
        self.win = pg.GraphicsLayoutWidget(show=True)
        layout.addWidget(self.win)

        # Create subplots
        self.p_speed = self.win.addPlot(title="Speed (km/h)")
        self.win.nextRow()
        self.p_delta = self.win.addPlot(title="Time Delta vs Best (seconds)")
        self.win.nextRow()
        self.p_throttle = self.win.addPlot(title="Pedals (Throttle/Brake %)")
        self.p_throttle.setYRange(0, 100)

        # Link X-axes
        self.p_delta.setXLink(self.p_speed)
        self.p_throttle.setXLink(self.p_speed)

        # Plot items: List of curves for each lap
        self.speed_curves = []
        self.throttle_curves = []
        self.brake_curves = []

        # Best lap curves (Cyan) - ZValue 50, thinner line
        self.best_speed_curve = self.p_speed.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine))
        self.best_speed_curve.setZValue(50)
        self.best_throttle_curve = self.p_throttle.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine))
        self.best_throttle_curve.setZValue(50)
        self.best_brake_curve = self.p_throttle.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine))
        self.best_brake_curve.setZValue(50)

        # Delta curve
        self.delta_curve = self.p_delta.plot(pen=pg.mkPen('y', width=2))
        self.p_delta.addLine(y=0, pen=pg.mkPen('w', style=QtCore.Qt.DotLine))

        # Current lap curves (distinct color) - ZValue 100, thicker line
        self.curr_speed_curve = self.p_speed.plot(pen=pg.mkPen('w', width=3))
        self.curr_speed_curve.setZValue(100)
        self.curr_throttle_curve = self.p_throttle.plot(pen=pg.mkPen('g', width=3))
        self.curr_throttle_curve.setZValue(100)
        self.curr_brake_curve = self.p_throttle.plot(pen=pg.mkPen('r', width=3))
        self.curr_brake_curve.setZValue(100)

        # Timer for UI updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(50) # 20 Hz update is usually enough for smooth display

    def update_plots(self):
        with self.telemetry_data.lock:
            laps = list(self.telemetry_data.laps)
            current = self.telemetry_data.current_lap_data
            best = self.telemetry_data.best_lap_data
            max_laps = self.telemetry_data.max_laps
            track_name = self.telemetry_data.track_name

            self.setWindowTitle(f"SimHub Real-Time Telemetry Plotter - {track_name}")

            # Update Best Lap
            if best and best["distance"]:
                n = min(len(best["distance"]), len(best["speed"]))
                self.best_speed_curve.setData(best["distance"][:n], best["speed"][:n])
                self.best_throttle_curve.setData(best["distance"][:n], best["throttle"][:n])
                self.best_brake_curve.setData(best["distance"][:n], best["brake"][:n])
                self.best_speed_curve.show()
                self.best_throttle_curve.show()
                self.best_brake_curve.show()
            else:
                self.best_speed_curve.hide()
                self.best_throttle_curve.hide()
                self.best_brake_curve.hide()

            # Update Current Lap and Delta
            if current["distance"] and current["speed"]:
                n = min(len(current["distance"]), len(current["speed"]), 
                        len(current["throttle"]), len(current["brake"]), len(current["time"]))

                curr_dist = np.array(current["distance"][:n])
                curr_time = np.array(current["time"][:n])

                self.curr_speed_curve.setData(curr_dist, current["speed"][:n])
                self.curr_throttle_curve.setData(curr_dist, current["throttle"][:n])
                self.curr_brake_curve.setData(curr_dist, current["brake"][:n])

                # Calculate Delta if best lap exists
                if best and len(best["distance"]) > 10:
                    # Interpolate best lap time at current distances
                    best_time_interp = np.interp(curr_dist, best["distance"], best["time"])
                    delta = curr_time - best_time_interp
                    self.delta_curve.setData(curr_dist, delta)
                    self.delta_curve.show()
                else:
                    self.delta_curve.hide()


            # Manage history curves
            num_history = len(laps)
            
            # Ensure we have enough curve items
            while len(self.speed_curves) < num_history:
                s_curve = self.p_speed.plot()
                s_curve.setZValue(1)
                self.speed_curves.append(s_curve)
                
                t_curve = self.p_throttle.plot()
                t_curve.setZValue(1)
                self.throttle_curves.append(t_curve)
                
                b_curve = self.p_throttle.plot()
                b_curve.setZValue(1)
                self.brake_curves.append(b_curve)
            
            # Hide unused curves if any
            for i in range(num_history, len(self.speed_curves)):
                self.speed_curves[i].hide()
                self.throttle_curves[i].hide()
                self.brake_curves[i].hide()

            # Update history curves with fading and shape safety
            for i, lap in enumerate(laps):
                age = num_history - i 
                alpha = int(max(20, 255 * (1.0 - (age / (max_laps + 1)))))
                
                speed_pen = pg.mkPen((200, 200, 200, alpha), width=1)
                throttle_pen = pg.mkPen((0, 255, 0, alpha), width=1)
                brake_pen = pg.mkPen((255, 0, 0, alpha), width=1)

                n = min(len(lap["distance"]), len(lap["speed"]), 
                        len(lap["throttle"]), len(lap["brake"]))

                self.speed_curves[i].setData(lap["distance"][:n], lap["speed"][:n])
                self.speed_curves[i].setPen(speed_pen)
                self.speed_curves[i].show()

                self.throttle_curves[i].setData(lap["distance"][:n], lap["throttle"][:n])
                self.throttle_curves[i].setPen(throttle_pen)
                self.throttle_curves[i].show()

                self.brake_curves[i].setData(lap["distance"][:n], lap["brake"][:n])
                self.brake_curves[i].setPen(brake_pen)
                self.brake_curves[i].show()

def main():
    parser = argparse.ArgumentParser(description="F1 25 Real-Time Telemetry Plotter (Direct Binary)")
    parser.add_argument("--laps", type=int, default=5, help="Number of previous laps to show")
    parser.add_argument("--port", type=int, default=DEFAULT_UDP_PORT, help="UDP Listening Port")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    
    telemetry_data = TelemetryData(max_laps=args.laps)
    
    listener = TelemetryListener(args.port)
    listener.track_received.connect(telemetry_data.update_track)
    listener.lap_received.connect(telemetry_data.update_lap)
    listener.telemetry_received.connect(telemetry_data.update_telemetry)
    listener.start()
    
    window = PlotterWindow(telemetry_data)
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
