import threading
import json
import os
from datetime import datetime
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

TEAM_COLORS = {
    0: (39, 244, 210), 1: (232, 0, 32), 2: (54, 113, 198), 3: (100, 196, 255),
    4: (34, 153, 113), 5: (0, 147, 204), 6: (102, 146, 255), 7: (182, 186, 189),
    8: (255, 128, 0), 9: (82, 226, 82), 41: (150, 150, 150), 104: (255, 255, 255)
}

SESSION_RACE = [15, 16, 17]
SESSION_TIME_TRIAL = [18]

class TelemetryData:
    def __init__(self, max_laps=5):
        self.max_laps = max_laps
        self.car_histories = {i: deque(maxlen=max_laps) for i in range(22)}
        self.player_idx = 0
        self.pb_car_idx = 255
        self.rival_car_idx = 255
        self.current_lap_num = -1
        self.session_type = 0
        self.track_name = "F1 25 Session"
        self.first_data_received = False
        self.all_cars_data = {i: self._new_lap_dict() for i in range(22)}
        self.all_cars_team_ids = [41] * 22
        
        self.car_latches = {i: {
            "speed_mph": 0.0, "rpm": 0, "throttle": 0.0, "brake": 0.0,
            "ers": 0.0, "tyre": 0.0, 
            "last_dist": -1.0, "last_lap": -1,
            "world_x": None, "world_y": None, "world_z": None,
            "last_motion_time": 0.0,
            "last_lap_distance": 0.0,
            "last_lap_data_time": 0.0,
            "dist_since_last_lap": 0.0,
            "last_frame_id": -1
        } for i in range(22)}

        self.current_lap_data = self.all_cars_data[0]
        self.best_lap_data = None
        self.best_lap_time = float('inf')
        self.is_recording = False
        self.recording_log = []
        self.recording_filename = ""
        self.marker_dist = None
        self.lock = threading.RLock()

    def _new_lap_dict(self):
        return {
            "distance": [], "speed": [], "rpm": [], "throttle": [], 
            "brake": [], "time": [], "tyre_wear": [], "ers_store": [],
            "pos_x": [], "pos_z": []
        }

    def toggle_recording(self):
        with self.lock:
            if not self.is_recording:
                self.is_recording = True
                self.recording_log = [{"metadata": {"game": "F1 25", "track": self.track_name, "timestamp": datetime.now().isoformat(), "units": {"speed": "mph"}}}]
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.recording_filename = f"F125_{self.track_name.replace(' ', '_')}_{timestamp}.json"
                print(f"REC: Started recording to {self.recording_filename}")
            else:
                self.is_recording = False
                if self.recording_log:
                    if not os.path.exists("recordings"): os.makedirs("recordings")
                    filepath = os.path.join("recordings", self.recording_filename)
                    with open(filepath, 'w') as f: json.dump(self.recording_log, f)
                    print(f"REC: Saved to {filepath}")
                self.recording_log = []

    def update_session(self, track_id, session_type, player_idx):
        with self.lock:
            self.player_idx = player_idx
            new_track = TRACK_MAP.get(track_id, f"Track {track_id}")
            if new_track != self.track_name or session_type != self.session_type:
                self.track_name = new_track
                self.session_type = session_type
                for h in self.car_histories.values(): h.clear()
                self.best_lap_data = None
                self.best_lap_time = float('inf')
                self.all_cars_data = {i: self._new_lap_dict() for i in range(22)}
                self.current_lap_data = self.all_cars_data[player_idx]

    def update_tt_indices(self, pb_idx, rival_idx):
        with self.lock:
            if pb_idx != self.pb_car_idx or rival_idx != self.rival_car_idx:
                print(f"TT: PlayerIdx={self.player_idx}, PBIdx={pb_idx}, RivalIdx={rival_idx}")
            self.pb_car_idx = pb_idx
            self.rival_car_idx = rival_idx

    def set_marker(self, dist):
        with self.lock:
            self.marker_dist = dist

    def update_participants(self, participants):
        with self.lock:
            for i, team_id in participants.items():
                if i < 22: self.all_cars_team_ids[i] = team_id

    def update_status(self, car_idx, ers_store, ers_deployed):
        with self.lock:
            if car_idx < 22: self.car_latches[car_idx]["ers"] = (ers_store / 4000000.0) * 100.0

    def update_damage(self, car_idx, tyres_wear):
        with self.lock:
            if car_idx < 22: self.car_latches[car_idx]["tyre"] = max(tyres_wear)

    def update_motion(self, car_idx, x, y, z, vx, vy, vz, session_time, frame_id):
        with self.lock:
            if car_idx < 22:
                latch = self.car_latches[car_idx]
                
                # 1. Calculate speed from world position delta
                speed_mph = latch["speed_mph"]
                if latch["world_x"] is not None and session_time > latch["last_motion_time"]:
                    dt = session_time - latch["last_motion_time"]
                    dx = x - latch["world_x"]; dy = y - latch["world_y"]; dz = z - latch["world_z"]
                    ds = (dx**2 + dy**2 + dz**2)**0.5
                    speed_ms = ds / dt
                    speed_mph = speed_ms * 2.23694
                    latch["dist_since_last_lap"] += ds
                
                latch["world_x"] = x; latch["world_y"] = y; latch["world_z"] = z
                latch["last_motion_time"] = session_time
                latch["speed_mph"] = speed_mph

                # 2. Record high-resolution data point
                if frame_id != latch["last_frame_id"] and latch["last_lap_data_time"] > 0:
                    data = self.all_cars_data[car_idx]
                    current_dist = latch["last_lap_distance"] + latch["dist_since_last_lap"]
                    
                    if current_dist >= 0 and (not data["distance"] or current_dist > data["distance"][-1]):
                        data["distance"].append(current_dist)
                        data["speed"].append(speed_mph)
                        data["time"].append(session_time)
                        data["rpm"].append(latch["rpm"])
                        data["throttle"].append(latch["throttle"])
                        data["brake"].append(latch["brake"])
                        data["tyre_wear"].append(latch["tyre"])
                        data["ers_store"].append(latch["ers"])
                        data["pos_x"].append(x)
                        data["pos_z"].append(z)
                    
                    latch["last_frame_id"] = frame_id

    def update_lap(self, car_idx, lap_num, distance, time_ms, session_time, frame_id):
        if car_idx == self.player_idx: self.first_data_received = True
        with self.lock:
            if car_idx >= 22: return
            latch = self.car_latches[car_idx]
            
            # Detect Lap Completion vs Session/Lap Reset
            if latch["last_lap"] != -1:
                if lap_num > latch["last_lap"]:
                    # NORMAL LAP COMPLETION
                    old_data = self.all_cars_data[car_idx]
                    if len(old_data["distance"]) > 100:
                        lap_time = old_data["time"][-1] - old_data["time"][0] if len(old_data["time"]) > 1 else float('inf')
                        if car_idx == self.player_idx:
                            if lap_time < self.best_lap_time:
                                self.best_lap_time = lap_time
                                self.best_lap_data = {k: list(v) for k, v in old_data.items()}
                        
                        self.car_histories[car_idx].append({k: list(v) for k, v in old_data.items()})
                    
                    # Reset current lap
                    self.all_cars_data[car_idx] = self._new_lap_dict()
                    if car_idx == self.player_idx: self.current_lap_data = self.all_cars_data[car_idx]
                    latch["dist_since_last_lap"] = 0

                elif lap_num < latch["last_lap"] or distance < latch["last_dist"] - 500:
                    # RESET / FLASHBACK (Major jump backwards)
                    self.all_cars_data[car_idx] = self._new_lap_dict()
                    if car_idx == self.player_idx: self.current_lap_data = self.all_cars_data[car_idx]
                    latch["dist_since_last_lap"] = 0

            latch["last_dist"] = distance
            latch["last_lap"] = lap_num
            latch["last_lap_distance"] = distance
            latch["last_lap_data_time"] = session_time
            latch["dist_since_last_lap"] = 0
            
            if car_idx == self.player_idx: self.current_lap_num = lap_num

    def update_telemetry(self, car_idx, speed_kph, rpm, throttle, brake, session_time, frame_id):
        with self.lock:
            if car_idx >= 22: return
            latch = self.car_latches[car_idx]
            latch["rpm"] = int(rpm)
            latch["throttle"] = float(throttle * 100.0)
            latch["brake"] = float(brake * 100.0)
