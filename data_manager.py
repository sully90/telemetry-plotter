import threading
from collections import deque

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
