import sys
import os
import argparse
import pandas as pd
import numpy as np
import json
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

from .data_manager import TelemetryData, TRACK_MAP
from .plotter import PlotterWindow, TrackMapWindow, SteeringWheelWindow
from .recorder import TelemetryRecorder

SESSION_TYPES = {
    0: "Unknown", 1: "P1", 2: "P2", 3: "P3", 4: "Short P", 
    5: "Q1", 6: "Q2", 7: "Q3", 8: "Short Q", 9: "OSQ", 
    10: "Sprint Q1", 11: "Sprint Q2", 12: "Sprint Q3",
    13: "Short Sprint Q", 14: "OS Sprint Q",
    15: "Race", 16: "Race 2", 17: "Race 3", 18: "Time Trial"
}

class PlaybackControls(QtWidgets.QWidget):
    seek_changed = QtCore.pyqtSignal(int)
    play_toggled = QtCore.pyqtSignal(bool)
    session_changed = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        
        self.btn_play = QtWidgets.QPushButton("Play")
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self._on_play_toggled)
        
        self.combo_session = QtWidgets.QComboBox()
        self.combo_session.currentIndexChanged.connect(self.session_changed.emit)
        self.combo_session.setMinimumWidth(150)
        
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.seek_changed.emit)
        
        self.lbl_time = QtWidgets.QLabel("00:00 / 00:00")
        
        layout.addWidget(self.btn_play)
        layout.addWidget(QtWidgets.QLabel("Session:"))
        layout.addWidget(self.combo_session)
        layout.addWidget(self.slider)
        layout.addWidget(self.lbl_time)

    def _on_play_toggled(self, checked):
        self.btn_play.setText("Pause" if checked else "Play")
        self.play_toggled.emit(checked)

    def set_sessions(self, session_labels):
        self.combo_session.blockSignals(True)
        self.combo_session.clear()
        self.combo_session.addItems(session_labels)
        self.combo_session.blockSignals(False)

    def set_range(self, max_val):
        self.slider.setRange(0, max_val)

    def set_value(self, val):
        self.slider.blockSignals(True)
        self.slider.setValue(val)
        self.slider.blockSignals(False)

    def set_time_labels(self, current_sec, total_sec):
        cur = f"{int(current_sec // 60):02d}:{int(current_sec % 60):02d}"
        tot = f"{int(total_sec // 60):02d}:{int(total_sec % 60):02d}"
        self.lbl_time.setText(f"{cur} / {tot}")

class PlaybackManager(QtCore.QObject):
    playback_finished = QtCore.pyqtSignal()
    session_info_ready = QtCore.pyqtSignal(list)

    def __init__(self, telemetry_data, df, metadata):
        super().__init__()
        self.telemetry_data = telemetry_data
        # Ensure data is sorted by time for consistent playback
        self.df = df.sort_values('time').reset_index(drop=True)
        self.metadata = metadata
        self.current_idx = 0
        self.is_playing = False
        self.current_laps = {} # car_idx -> lap_num
        self.current_session_idx = 0
        
        # Real-time sync
        self.playback_start_time = 0
        self.elapsed_timer = QtCore.QElapsedTimer()
        
        # Sessions extraction
        self.sessions = []
        self.session_labels = []
        self._extract_sessions()
        
        # Pre-populate lap data for current session
        self.laps_data = {} # car_idx -> {lap_num: lap_data}
        
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(33) # ~30 FPS for better UI performance
        
        self._initial_setup()

    def _extract_sessions(self):
        """Identify distinct sessions within the recorded data."""
        if 'session_type' not in self.df.columns or len(self.df) == 0:
            st = self.metadata.get("session_type", 0)
            self.sessions = [{"type": st, "start_idx": 0, "end_idx": len(self.df)-1}]
            self.session_labels = [f"{SESSION_TYPES.get(st, 'Unknown')} (Entire Recording)"]
            return

        sessions = []
        df = self.df
        
        # Find indices where session_type changes
        # Use a more robust way to find changes, ignoring small blips if necessary
        # but for UDP telemetry, it should be quite stable.
        types = df['session_type'].values
        change_indices = [0]
        for i in range(1, len(types)):
            if types[i] != types[i-1]:
                change_indices.append(i)
        
        change_indices.append(len(df))
        
        for i in range(len(change_indices) - 1):
            start = change_indices[i]
            end = change_indices[i+1] - 1
            if end < start: continue
            
            st = int(df.iloc[start]['session_type'])
            
            # Get lap range for this session block
            laps = df.iloc[start:end+1]['lap'].unique()
            lap_range = f"L{int(min(laps))}-{int(max(laps))}" if len(laps) > 0 else ""
            
            sessions.append({
                "type": st,
                "start_idx": start,
                "end_idx": end,
            })
            self.session_labels.append(f"{SESSION_TYPES.get(st, 'Unknown')} {lap_range} ({start}-{end})")
        
        self.sessions = sessions

    def select_session(self, session_idx):
        if session_idx < 0 or session_idx >= len(self.sessions):
            return
            
        print(f"Playback: Selecting session {session_idx}: {self.session_labels[session_idx]}")
        session = self.sessions[session_idx]
        self.current_session_idx = session_idx
        
        # Filter data for this session to cache laps
        session_df = self.df.iloc[session['start_idx'] : session['end_idx'] + 1]
        
        # Reset telemetry data state for the new session
        with self.telemetry_data.lock:
            self.telemetry_data.session_type = session['type']
            for h in self.telemetry_data.car_histories.values(): h.clear()
            self.telemetry_data.best_lap_data = None
            self.telemetry_data.best_lap_time = float('inf')
            self.telemetry_data.car_best_laps = {}
            self.telemetry_data.car_best_times = {}
            self.telemetry_data.all_cars_data = {i: self.telemetry_data._new_lap_dict() for i in range(22)}
            self.current_laps = {}
            
            # Update player/rival from metadata if available, otherwise guess
            self.telemetry_data.player_idx = self.metadata.get("player_idx", 0)
            self.telemetry_data.rival_car_idx = self.metadata.get("rival_car_idx", 255)

        # Re-cache laps for this session
        self._cache_session_laps(session_df)
        
        # Find best lap for EVERY car in THIS session
        with self.telemetry_data.lock:
            for car_idx, laps in self.laps_data.items():
                best_lap_time = float('inf')
                best_lap_data = None
                for lap_data in laps.values():
                    if len(lap_data["time"]) > 50: # Minimum points for a valid lap
                        # Ensure lap starts reasonably near the line
                        d_start = lap_data["distance"][0]
                        if d_start > 200: continue 

                        if lap_data.get("lap_time") and len(lap_data["lap_time"]) > 1:
                            lap_time = lap_data["lap_time"][-1] - lap_data["lap_time"][0]
                        else:
                            lap_time = lap_data["time"][-1] - lap_data["time"][0]
                        
                        if lap_time < best_lap_time:
                            best_lap_time = lap_time
                            best_lap_data = lap_data
                
                if best_lap_data:
                    self.telemetry_data.car_best_laps[car_idx] = best_lap_data
                    self.telemetry_data.car_best_times[car_idx] = best_lap_time
                    if car_idx == self.telemetry_data.player_idx:
                        self.telemetry_data.best_lap_data = best_lap_data
                        self.telemetry_data.best_lap_time = best_lap_time

        # Jump to start of session
        self.seek(session['start_idx'])

    def _cache_session_laps(self, df):
        """Cache all lap data from the given dataframe (subset of recording)."""
        self.laps_data = {}
        for car_idx, car_df in df.groupby('car_idx'):
            car_idx = int(car_idx)
            if car_idx >= 22: continue
            self.laps_data[car_idx] = {}
            for lap_num, lap_df in car_df.groupby('lap'):
                self.laps_data[car_idx][int(lap_num)] = {
                    "distance": lap_df['distance'].tolist(),
                    "speed": lap_df['speed'].tolist(),
                    "rpm": lap_df['rpm'].tolist(),
                    "throttle": lap_df['throttle'].tolist(),
                    "brake": lap_df['brake'].tolist(),
                    "steer": lap_df['steer'].tolist(),
                    "time": lap_df['time'].tolist(),
                    "lap_time": lap_df['lap_time'].tolist() if 'lap_time' in lap_df else [],
                    "tyre_wear": lap_df['tyre_wear'].tolist() if 'tyre_wear' in lap_df else [0]*len(lap_df), 
                    "ers_store": lap_df['ers_store'].tolist() if 'ers_store' in lap_df else [0]*len(lap_df),
                    "pos_x": lap_df['pos_x'].tolist(),
                    "pos_z": lap_df['pos_z'].tolist()
                }

    def _initial_setup(self):
        """Set up initial state for plotting."""
        self.telemetry_data.track_name = self.metadata.get("track", "Unknown")
        # Default to the first session found
        self.select_session(0)


    def set_playing(self, playing):
        if playing == self.is_playing:
            return
        self.is_playing = playing
        if playing:
            # Sync playback start to current_idx
            self.playback_start_time = self.df.iloc[self.current_idx]['time']
            self.elapsed_timer.start()

    def _on_tick(self):
        if not self.is_playing:
            return
            
        # Calculate how much sim time should have passed
        elapsed_sec = self.elapsed_timer.elapsed() / 1000.0
        target_sim_time = self.playback_start_time + elapsed_sec
        
        # Process all rows up to target_sim_time
        while self.current_idx < len(self.df) and self.df.iloc[self.current_idx]['time'] <= target_sim_time:
            self.update_telemetry_state()
            self.current_idx += 1
            
        if self.current_idx >= len(self.df):
            self.is_playing = False
            self.playback_finished.emit()

    def update_telemetry_state(self):
        if self.current_idx >= len(self.df):
            return
            
        row = self.df.iloc[self.current_idx]
        car_idx = int(row["car_idx"])
        lap_num = int(row["lap"])
        
        if car_idx >= 22:
            return
            
        with self.telemetry_data.lock:
            # Handle lap transitions for this car
            if car_idx not in self.current_laps or self.current_laps[car_idx] != lap_num:
                # If we were previously on a different lap, move it to history
                if car_idx in self.current_laps:
                    old_lap_data = self.telemetry_data.all_cars_data[car_idx]
                    if len(old_lap_data["distance"]) > 10:
                        self.telemetry_data.car_histories[car_idx].append({k: list(v) for k, v in old_lap_data.items()})

                # Load the new lap data into TelemetryData for plotting
                if car_idx in self.laps_data and lap_num in self.laps_data[car_idx]:
                    new_data = self.laps_data[car_idx][lap_num]
                    target = self.telemetry_data.all_cars_data[car_idx]
                    for k, v in new_data.items():
                        target[k] = v
                
                self.current_laps[car_idx] = lap_num
                if car_idx == self.telemetry_data.player_idx:
                    self.telemetry_data.current_lap_num = lap_num
                    self.telemetry_data.current_lap_data = self.telemetry_data.all_cars_data[car_idx]

            latch = self.telemetry_data.car_latches[car_idx]
            latch["speed_mph"] = row["speed"]
            latch["rpm"] = row["rpm"]
            latch["throttle"] = row["throttle"]
            latch["brake"] = row["brake"]
            latch["steer"] = row["steer"]
            latch["world_x"] = row["pos_x"]
            latch["world_z"] = row["pos_z"]
            latch["last_lap"] = lap_num
            
            # Update TT indices if present in row
            if "rival_car_idx" in row:
                self.telemetry_data.rival_car_idx = int(row["rival_car_idx"])
            if "pb_car_idx" in row:
                self.telemetry_data.pb_car_idx = int(row["pb_car_idx"])
            
            if car_idx == self.telemetry_data.player_idx:
                self.telemetry_data.marker_dist = row["distance"]

    def seek(self, index):
        self.current_idx = max(0, min(index, len(self.df) - 1))
        if self.is_playing:
            # Reset sync point
            self.playback_start_time = self.df.iloc[self.current_idx]['time']
            self.elapsed_timer.start()
        self.update_telemetry_state()

def main():
    parser = argparse.ArgumentParser(description="F1 25 Telemetry Playback")
    parser.add_argument("file", help="Path to .parquet recording")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    app = QtWidgets.QApplication(sys.argv)
    
    # Load data
    recorder = TelemetryRecorder()
    df = recorder.read_recording(args.file)
    
    # Extract metadata from Parquet (if we saved it correctly)
    import pyarrow.parquet as pq
    table = pq.read_table(args.file)
    metadata = {}
    if table.schema.metadata and b'telemetry_metadata' in table.schema.metadata:
        metadata = json.loads(table.schema.metadata[b'telemetry_metadata'].decode('utf-8'))
    
    telemetry_data = TelemetryData(max_laps=10)
    playback_mgr = PlaybackManager(telemetry_data, df, metadata)
    
    # Set up UI
    controls_window = QtWidgets.QMainWindow()
    controls_window.setWindowTitle(f"Playback: {os.path.basename(args.file)}")
    controls_window.resize(600, 100)
    
    controls = PlaybackControls(controls_window)
    controls_window.setCentralWidget(controls)
    controls.set_range(len(df) - 1)
    controls.set_sessions(playback_mgr.session_labels)
    
    def on_play_toggled(playing):
        playback_mgr.set_playing(playing)
        
    def on_playback_finished():
        controls.btn_play.setChecked(False)
        
    def on_seek(idx):
        playback_mgr.seek(idx)
        update_time_label()

    def update_time_label():
        row = df.iloc[playback_mgr.current_idx]
        total_time = df['time'].iloc[-1] - df['time'].iloc[0]
        current_time = row['time'] - df['time'].iloc[0]
        controls.set_time_labels(current_time, total_time)

    def on_session_changed(idx):
        playback_mgr.select_session(idx)
        session = playback_mgr.sessions[idx]
        controls.slider.setRange(session['start_idx'], session['end_idx'])
        controls.set_value(playback_mgr.current_idx)
        update_time_label()

    controls.play_toggled.connect(on_play_toggled)
    playback_mgr.playback_finished.connect(on_playback_finished)
    controls.seek_changed.connect(on_seek)
    controls.session_changed.connect(on_session_changed)
    
    # Update slider from manager
    def update_slider():
        if playback_mgr.is_playing:
            controls.set_value(playback_mgr.current_idx)
            update_time_label()
            
    timer = QtCore.QTimer()
    timer.timeout.connect(update_slider)
    timer.start(50)

    # Launch existing windows
    screens = app.screens()
    target_screen = screens[1] if len(screens) > 1 else screens[0]
    geom = target_screen.availableGeometry()
    width = geom.width() // 2
    height = geom.height()

    window = PlotterWindow(telemetry_data)
    window.setGeometry(geom.x(), geom.y(), width, height - 150)
    window.show()

    map_window = TrackMapWindow(telemetry_data)
    map_window.setGeometry(geom.x() + width, geom.y(), width, height - 150)
    map_window.show()
    
    steer_window = SteeringWheelWindow(telemetry_data)
    steer_window.setGeometry(geom.x() + geom.width() - 320, geom.y() + geom.height() - 420, 300, 300)
    steer_window.show()

    # Position controls at bottom
    controls_window.setGeometry(geom.x(), geom.y() + height - 150, geom.width(), 100)
    controls_window.show()
    
    # Connections
    map_window.request_toggle_tyre_wear.connect(window.toggle_tyre_wear)
    map_window.request_toggle_ers.connect(window.toggle_ers)
    window.marker_clicked.connect(telemetry_data.set_marker)
    map_window.marker_clicked.connect(telemetry_data.set_marker)
    window.view_range_changed.connect(map_window.focus_on_distance_range)
    map_window.request_reset_telemetry.connect(window.reset_zoom)
    
    update_time_label()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
