import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from data_manager import TEAM_COLORS, SESSION_RACE, SESSION_TIME_TRIAL

class TrackMapWindow(QtWidgets.QMainWindow):
    request_toggle_tyre_wear = QtCore.pyqtSignal()
    request_toggle_ers = QtCore.pyqtSignal()
    marker_clicked = QtCore.pyqtSignal(float)

    def __init__(self, telemetry_data):
        super().__init__()
        self.telemetry_data = telemetry_data
        self.setWindowTitle("F1 25 Track Map")
        self.resize(800, 800)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)
        self.win = pg.GraphicsLayoutWidget(show=True)
        layout.addWidget(self.win)

        self.p_map = self.win.addPlot(title="Track Map (X vs Z)")
        self.p_map.setAspectLocked(True)
        self.p_map.showGrid(x=True, y=True)

        # History curves for all cars
        self.history_curves = {i: [] for i in range(22)}
        
        # Opponents current lap lines
        self.opp_curves = {i: self.p_map.plot(pen=pg.mkPen((100, 100, 100, 100), width=1)) for i in range(22)}
        
        # Current position dots
        self.car_dots = pg.ScatterPlotItem(size=10, pen=pg.mkPen('w'), brush=pg.mkBrush('w'))
        self.p_map.addItem(self.car_dots)

        # Current lap curve for player (thick white)
        self.curr_curve = self.p_map.plot(pen=pg.mkPen('w', width=3))
        self.curr_curve.setZValue(100)

        # Marker (Yellow Cross)
        self.marker_point = pg.ScatterPlotItem(size=15, pen=pg.mkPen('y', width=2), brush=pg.mkBrush(0,0,0,0), symbol='+')
        self.marker_point.setZValue(200)
        self.p_map.addItem(self.marker_point)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(50)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Q:
            QtWidgets.QApplication.instance().quit()
        elif event.key() == QtCore.Qt.Key_Space:
            with self.telemetry_data.lock: self.telemetry_data.marker_dist = None
        elif event.key() == QtCore.Qt.Key_R:
            self.telemetry_data.toggle_recording()
        elif event.key() == QtCore.Qt.Key_E:
            self.request_toggle_ers.emit()
        elif event.key() == QtCore.Qt.Key_T:
            self.request_toggle_tyre_wear.emit()
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MidButton:
            try:
                pos = event.pos()
                scene_pos = self.win.mapToScene(pos)
                plot_pos = self.p_map.vb.mapSceneToView(scene_pos)
                
                # Find nearest point in player's current lap
                with self.telemetry_data.lock:
                    data = self.telemetry_data.current_lap_data
                    if data["pos_x"]:
                        px = np.array(data["pos_x"])
                        pz = np.array(data["pos_z"])
                        dists = (px - plot_pos.x())**2 + (pz - plot_pos.y())**2
                        idx = np.argmin(dists)
                        self.marker_clicked.emit(data["distance"][idx])
            except Exception as e:
                print(f"Error handling map click: {e}")
        super().mousePressEvent(event)

    def focus_on_distance_range(self, dist_min, dist_max):
        # Find world coordinates for this distance range to sync zoom
        try:
            with self.telemetry_data.lock:
                data = self.telemetry_data.current_lap_data
                if data["distance"] and len(data["distance"]) > 1 and data["pos_x"]:
                    d = np.array(data["distance"])
                    mask = (d >= dist_min) & (d <= dist_max)
                    if np.any(mask):
                        x_pts = np.array(data["pos_x"])[mask]
                        z_pts = np.array(data["pos_z"])[mask]
                        if len(x_pts) > 0:
                            self.p_map.setRange(xRange=(np.min(x_pts), np.max(x_pts)), yRange=(np.min(z_pts), np.max(z_pts)), padding=0.1)
        except Exception as e:
            print(f"Error syncing zoom: {e}")

    def update_plots(self):
        with self.telemetry_data.lock:
            player_idx = self.telemetry_data.player_idx
            rival_idx = self.telemetry_data.rival_car_idx
            is_tt = self.telemetry_data.session_type in SESSION_TIME_TRIAL
            
            # Update dots (current positions)
            spots = []
            for i in range(22):
                latch = self.telemetry_data.car_latches[i]
                if latch["world_x"] is not None:
                    team_id = self.telemetry_data.all_cars_team_ids[i]
                    color = TEAM_COLORS.get(team_id, (200, 200, 200))
                    if i == player_idx: color = (255, 255, 255); size = 12; symbol = 't'
                    elif i == rival_idx and is_tt: color = (200, 0, 255); size = 12; symbol = 'o'
                    else: size = 10; symbol = 'o'
                    
                    spots.append({
                        'pos': (latch["world_x"], latch["world_z"]),
                        'size': size,
                        'pen': pg.mkPen(color),
                        'brush': pg.mkBrush((*color, 255)),
                        'symbol': symbol
                    })
            self.car_dots.setData(spots)

            # Update Opponents / Rival lines
            for i in range(22):
                if i == player_idx:
                    self.opp_curves[i].hide()
                    continue
                
                car_data = self.telemetry_data.all_cars_data[i]
                if car_data["pos_x"]:
                    team_id = self.telemetry_data.all_cars_team_ids[i]
                    color = TEAM_COLORS.get(team_id, (150, 150, 150))
                    alpha = 150 if (i == rival_idx and is_tt) else 60
                    width = 2 if (i == rival_idx and is_tt) else 1
                    
                    self.opp_curves[i].setPen(pg.mkPen((*color, alpha), width=width))
                    self.opp_curves[i].setData(car_data["pos_x"], car_data["pos_z"])
                    self.opp_curves[i].show()
                else:
                    self.opp_curves[i].hide()

            # Update Player Current Lap
            player_data = self.telemetry_data.all_cars_data[player_idx]
            if player_data["pos_x"]:
                self.curr_curve.setData(player_data["pos_x"], player_data["pos_z"])
                self.curr_curve.show()
            else:
                self.curr_curve.hide()

            # Update Car Histories (fading)
            for i in range(22):
                history = list(self.telemetry_data.car_histories[i])
                num_history = len(history)
                
                while len(self.history_curves[i]) < num_history:
                    c = self.p_map.plot()
                    c.setZValue(1)
                    self.history_curves[i].append(c)
                
                for j in range(num_history, len(self.history_curves[i])):
                    self.history_curves[i][j].hide()

                if i == player_idx:
                    base_color = (255, 255, 255)
                elif i == rival_idx and is_tt:
                    base_color = (200, 0, 255)
                else:
                    team_id = self.telemetry_data.all_cars_team_ids[i]
                    base_color = TEAM_COLORS.get(team_id, (150, 150, 150))

                for j, lap in enumerate(history):
                    age = num_history - j
                    alpha = int(max(10, 180 * (1.0 - (age / (self.telemetry_data.max_laps + 1)))))
                    if lap["pos_x"]:
                        self.history_curves[i][j].setData(lap["pos_x"], lap["pos_z"])
                        self.history_curves[i][j].setPen(pg.mkPen((*base_color, alpha), width=1))
                        self.history_curves[i][j].show()
                    else:
                        self.history_curves[i][j].hide()

            # Update shared marker
            marker_dist = self.telemetry_data.marker_dist
            if marker_dist is not None:
                if player_data["distance"]:
                    mx = np.interp(marker_dist, player_data["distance"], player_data["pos_x"])
                    mz = np.interp(marker_dist, player_data["distance"], player_data["pos_z"])
                    self.marker_point.setData([{'pos': (mx, mz)}])
                    self.marker_point.show()
                else: self.marker_point.hide()
            else: self.marker_point.hide()

class PlotterWindow(QtWidgets.QMainWindow):
    marker_clicked = QtCore.pyqtSignal(float)
    view_range_changed = QtCore.pyqtSignal(float, float)

    def __init__(self, telemetry_data):
        super().__init__()
        self.telemetry_data = telemetry_data
        self.setWindowTitle("F1 25 Real-Time Telemetry Plotter")
        self.resize(1200, 1000)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)
        self.win = pg.GraphicsLayoutWidget(show=True)
        layout.addWidget(self.win)

        # Create subplots
        self.p_speed = self.win.addPlot(title="Speed (mph)")
        self.win.nextRow()
        self.p_delta = self.win.addPlot(title="Time Delta vs Reference (seconds)")
        self.win.nextRow()
        self.p_throttle = self.win.addPlot(title="Pedals (Throttle/Brake %)")
        self.win.nextRow()
        self.p_tyre = self.win.addPlot(title="Max Tyre Wear (%)")
        self.win.nextRow()
        self.p_ers = self.win.addPlot(title="ERS Battery Store (%)")
        self.p_ers.setYRange(0, 100)

        # Link X-axes
        self.p_delta.setXLink(self.p_speed); self.p_throttle.setXLink(self.p_speed)
        self.p_tyre.setXLink(self.p_speed); self.p_ers.setXLink(self.p_speed)

        # Sync zoom to Map
        self.p_speed.sigXRangeChanged.connect(self._handle_range_change)

        # Visibility
        self.show_tyre_wear = False; self.show_ers = False
        self.p_tyre.hide(); self.p_ers.hide()

        # Curves
        self.history_speed_curves = []; self.history_throttle_curves = []
        self.history_brake_curves = []; self.history_tyre_curves = []; self.history_ers_curves = []

        # Opponents / Race Mode
        self.opp_speed_curves = {i: self.p_speed.plot(pen=pg.mkPen((100, 100, 100, 50), width=1)) for i in range(22)}
        self.opp_throttle_curves = {i: self.p_throttle.plot(pen=pg.mkPen((0, 150, 0, 50), width=1)) for i in range(22)}
        self.opp_brake_curves = {i: self.p_throttle.plot(pen=pg.mkPen((150, 0, 0, 50), width=1)) for i in range(22)}
        self.opp_tyre_curves = {i: self.p_tyre.plot(pen=pg.mkPen((150, 150, 150, 50), width=1)) for i in range(22)}
        self.opp_ers_curves = {i: self.p_ers.plot(pen=pg.mkPen((100, 100, 200, 50), width=1)) for i in range(22)}
        for d in [self.opp_speed_curves, self.opp_throttle_curves, self.opp_brake_curves, self.opp_tyre_curves, self.opp_ers_curves]:
            for c in d.values(): c.setZValue(2)

        # Best Lap (Cyan Dash)
        self.best_speed_curve = self.p_speed.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine)); self.best_speed_curve.setZValue(50)
        self.best_throttle_curve = self.p_throttle.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine)); self.best_throttle_curve.setZValue(50)
        self.best_brake_curve = self.p_throttle.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine)); self.best_brake_curve.setZValue(50)
        self.best_tyre_curve = self.p_tyre.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine)); self.best_tyre_curve.setZValue(50)
        self.best_ers_curve = self.p_ers.plot(pen=pg.mkPen('c', width=1, style=QtCore.Qt.DashLine)); self.best_ers_curve.setZValue(50)

        # Rival Ghost (Purple Dash) - New
        self.rival_speed_curve = self.p_speed.plot(pen=pg.mkPen((200, 0, 255), width=1, style=QtCore.Qt.DashLine)); self.rival_speed_curve.setZValue(51)
        self.rival_throttle_curve = self.p_throttle.plot(pen=pg.mkPen((200, 0, 255), width=1, style=QtCore.Qt.DashLine)); self.rival_throttle_curve.setZValue(51)
        self.rival_brake_curve = self.p_throttle.plot(pen=pg.mkPen((200, 0, 255), width=1, style=QtCore.Qt.DashLine)); self.rival_brake_curve.setZValue(51)

        # Delta
        self.delta_curve = self.p_delta.plot(pen=pg.mkPen('y', width=2))
        self.p_delta.addLine(y=0, pen=pg.mkPen('w', style=QtCore.Qt.DotLine))

        # Current Lap (Solid)
        self.curr_speed_curve = self.p_speed.plot(pen=pg.mkPen('w', width=3)); self.curr_speed_curve.setZValue(100)
        self.curr_throttle_curve = self.p_throttle.plot(pen=pg.mkPen('g', width=3)); self.curr_throttle_curve.setZValue(100)
        self.curr_brake_curve = self.p_throttle.plot(pen=pg.mkPen('r', width=3)); self.curr_brake_curve.setZValue(100)
        self.curr_tyre_curve = self.p_tyre.plot(pen=pg.mkPen('m', width=3)); self.curr_tyre_curve.setZValue(100)
        self.curr_ers_curve = self.p_ers.plot(pen=pg.mkPen('b', width=3)); self.curr_ers_curve.setZValue(100)

        # Shared Marker (Vertical Yellow lines)
        self.marker_lines = []
        for p in [self.p_speed, self.p_delta, self.p_throttle, self.p_tyre, self.p_ers]:
            line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('y', width=1, style=QtCore.Qt.DashLine))
            line.setZValue(200)
            p.addItem(line)
            self.marker_lines.append(line)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(50)

    def toggle_tyre_wear(self):
        self.show_tyre_wear = not self.show_tyre_wear
        if self.show_tyre_wear: self.p_tyre.show()
        else: self.p_tyre.hide()

    def toggle_ers(self):
        self.show_ers = not self.show_ers
        if self.show_ers: self.p_ers.show()
        else: self.p_ers.hide()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Q:
            QtWidgets.QApplication.instance().quit()
        elif event.key() == QtCore.Qt.Key_Space:
            with self.telemetry_data.lock: self.telemetry_data.marker_dist = None
        elif event.key() == QtCore.Qt.Key_T:
            self.toggle_tyre_wear()
        elif event.key() == QtCore.Qt.Key_E:
            self.toggle_ers()
        elif event.key() == QtCore.Qt.Key_R:
            self.telemetry_data.toggle_recording()
        super().keyPressEvent(event)

    def _handle_range_change(self, window, view_range):
        self.view_range_changed.emit(view_range[0], view_range[1])

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MidButton:
            try:
                pos = event.pos()
                scene_pos = self.win.mapToScene(pos)
                # Find which plot was clicked
                for p in [self.p_speed, self.p_delta, self.p_throttle, self.p_tyre, self.p_ers]:
                    if p.sceneBoundingRect().contains(scene_pos):
                        view_pos = p.vb.mapSceneToView(scene_pos)
                        self.marker_clicked.emit(view_pos.x())
                        break
            except Exception as e:
                print(f"Error handling telemetry click: {e}")
        super().mousePressEvent(event)


    def update_plots(self):
        with self.telemetry_data.lock:
            player_idx = self.telemetry_data.player_idx
            rival_idx = self.telemetry_data.rival_car_idx
            session_type = self.telemetry_data.session_type
            is_race = session_type in SESSION_RACE
            is_tt = session_type in SESSION_TIME_TRIAL
            is_recording = self.telemetry_data.is_recording
            
            track_name = self.telemetry_data.track_name
            mode_str = "RACE MODE" if is_race else "TIME TRIAL" if is_tt else "PRACTICE"
            rec_str = " [RECORDING]" if is_recording else ""
            self.setWindowTitle(f"F1 25 Telemetry - {track_name} [{mode_str}]{rec_str} (T:Tyre, E:Energy, R:Record, Space:Clear)")

            # Update Opponents / Rival Ghost
            for i in range(22):
                car_data = self.telemetry_data.all_cars_data[i]
                if i == player_idx or not car_data["distance"]:
                    self.opp_speed_curves[i].hide(); self.opp_throttle_curves[i].hide()
                    self.opp_brake_curves[i].hide(); self.opp_tyre_curves[i].hide(); self.opp_ers_curves[i].hide()
                    if i == rival_idx: 
                        self.rival_speed_curve.hide(); self.rival_throttle_curve.hide(); self.rival_brake_curve.hide()
                    continue
                
                # Special handling for Rival Ghost in TT
                if is_tt and i == rival_idx:
                    n = min(len(car_data["distance"]), len(car_data["speed"]))
                    self.rival_speed_curve.setData(car_data["distance"][:n], car_data["speed"][:n]); self.rival_speed_curve.show()
                    self.rival_throttle_curve.setData(car_data["distance"][:n], car_data["throttle"][:n]); self.rival_throttle_curve.show()
                    self.rival_brake_curve.setData(car_data["distance"][:n], car_data["brake"][:n]); self.rival_brake_curve.show()
                    self.opp_speed_curves[i].hide() # Don't show faint opponent curve for rival
                elif is_race:
                    team_id = self.telemetry_data.all_cars_team_ids[i]
                    color = TEAM_COLORS.get(team_id, (150, 150, 150))
                    n = min(len(car_data["distance"]), len(car_data["speed"]), len(car_data["throttle"]), len(car_data["brake"]))
                    self.opp_speed_curves[i].setPen(pg.mkPen((*color, 80), width=1)); self.opp_speed_curves[i].setData(car_data["distance"][:n], car_data["speed"][:n]); self.opp_speed_curves[i].show()
                    self.opp_throttle_curves[i].setPen(pg.mkPen((*color, 80), width=1)); self.opp_throttle_curves[i].setData(car_data["distance"][:n], car_data["throttle"][:n]); self.opp_throttle_curves[i].show()
                    self.opp_brake_curves[i].setPen(pg.mkPen((*color, 80), width=1)); self.opp_brake_curves[i].setData(car_data["distance"][:n], car_data["brake"][:n]); self.opp_brake_curves[i].show()
                    if self.show_tyre_wear and car_data["tyre_wear"]:
                        nt = min(len(car_data["distance"]), len(car_data["tyre_wear"]))
                        self.opp_tyre_curves[i].setPen(pg.mkPen((*color, 80), width=1)); self.opp_tyre_curves[i].setData(car_data["distance"][:nt], car_data["tyre_wear"][:nt]); self.opp_tyre_curves[i].show()
                    if self.show_ers and car_data["ers_store"]:
                        ne = min(len(car_data["distance"]), len(car_data["ers_store"]))
                        self.opp_ers_curves[i].setPen(pg.mkPen((*color, 80), width=1)); self.opp_ers_curves[i].setData(car_data["distance"][:ne], car_data["ers_store"][:ne]); self.opp_ers_curves[i].show()
                else:
                    self.opp_speed_curves[i].hide()

            # Update Session Best (Cyan)
            best = self.telemetry_data.best_lap_data
            if best and best["distance"] and (is_tt or not is_race):
                n = min(len(best["distance"]), len(best["speed"]))
                self.best_speed_curve.setData(best["distance"][:n], best["speed"][:n]); self.best_speed_curve.show()
                self.best_throttle_curve.setData(best["distance"][:n], best["throttle"][:n]); self.best_throttle_curve.show()
                self.best_brake_curve.setData(best["distance"][:n], best["brake"][:n]); self.best_brake_curve.show()
                if self.show_tyre_wear and best["tyre_wear"]:
                    nt = min(len(best["distance"]), len(best["tyre_wear"]))
                    self.best_tyre_curve.setData(best["distance"][:nt], best["tyre_wear"][:nt]); self.best_tyre_curve.show()
                if self.show_ers and best["ers_store"]:
                    ne = min(len(best["distance"]), len(best["ers_store"]))
                    self.best_ers_curve.setData(best["distance"][:ne], best["ers_store"][:ne]); self.best_ers_curve.show()
            else:
                self.best_speed_curve.hide(); self.best_tyre_curve.hide(); self.best_ers_curve.hide()

            # Update Current Lap & Delta
            current = self.telemetry_data.current_lap_data
            if current["distance"] and current["speed"]:
                n = min(len(current["distance"]), len(current["speed"]), len(current["throttle"]), len(current["brake"]), len(current["time"]))
                curr_dist = np.array(current["distance"][:n]); curr_time = np.array(current["time"][:n])
                self.curr_speed_curve.setData(curr_dist, current["speed"][:n])
                self.curr_throttle_curve.setData(curr_dist, current["throttle"][:n])
                self.curr_brake_curve.setData(curr_dist, current["brake"][:n])
                if self.show_tyre_wear and current["tyre_wear"]:
                    nt = min(len(current["distance"]), len(current["tyre_wear"])); self.curr_tyre_curve.setData(current["distance"][:nt], current["tyre_wear"][:nt]); self.curr_tyre_curve.show()
                if self.show_ers and current["ers_store"]:
                    ne = min(len(current["distance"]), len(current["ers_store"])); self.curr_ers_curve.setData(current["distance"][:ne], current["ers_store"][:ne]); self.curr_ers_curve.show()
                
                # Delta logic: Prefer Rival Ghost if in TT and available, otherwise Session Best
                ref_lap = None
                if is_tt and rival_idx != 255: ref_lap = self.telemetry_data.all_cars_data[rival_idx]
                elif is_tt or not is_race: ref_lap = best
                
                if ref_lap and len(ref_lap["distance"]) > 10:
                    ref_time = np.array(ref_lap["time"])
                    ref_time_rel = ref_time - ref_time[0]
                    curr_time_rel = curr_time - curr_time[0]
                    
                    best_time_interp = np.interp(curr_dist, ref_lap["distance"], ref_time_rel)
                    delta = curr_time_rel - best_time_interp
                    ref_name = "Rival" if ref_lap == self.telemetry_data.all_cars_data.get(rival_idx) else "Best"
                    self.p_delta.setTitle(f"Time Delta vs {ref_name} (seconds)")
                    self.delta_curve.setData(curr_dist, delta); self.p_delta.show()
                else: self.p_delta.hide()

            # Update Player History
            laps = list(self.telemetry_data.car_histories[player_idx])
            num_history = len(laps)
            while len(self.history_speed_curves) < num_history:
                s = self.p_speed.plot(); s.setZValue(1); self.history_speed_curves.append(s)
                t = self.p_throttle.plot(); t.setZValue(1); self.history_throttle_curves.append(t)
                b = self.p_throttle.plot(); b.setZValue(1); self.history_brake_curves.append(b)
                y = self.p_tyre.plot(); y.setZValue(1); self.history_tyre_curves.append(y)
                e = self.p_ers.plot(); e.setZValue(1); self.history_ers_curves.append(e)
            for i, lap in enumerate(laps):
                age = num_history - i; alpha = int(max(20, 255 * (1.0 - (age / (self.telemetry_data.max_laps + 1)))))
                n = min(len(lap["distance"]), len(lap["speed"]), len(lap["throttle"]), len(lap["brake"]))
                self.history_speed_curves[i].setData(lap["distance"][:n], lap["speed"][:n]); self.history_speed_curves[i].setPen(pg.mkPen((200, 200, 200, alpha), width=1)); self.history_speed_curves[i].show()
                self.history_throttle_curves[i].setData(lap["distance"][:n], lap["throttle"][:n]); self.history_throttle_curves[i].setPen(pg.mkPen((0, 255, 0, alpha), width=1)); self.history_throttle_curves[i].show()
                self.history_brake_curves[i].setData(lap["distance"][:n], lap["brake"][:n]); self.history_brake_curves[i].setPen(pg.mkPen((255, 0, 0, alpha), width=1)); self.history_brake_curves[i].show()
                if self.show_tyre_wear and lap["tyre_wear"]:
                    nt = min(len(lap["distance"]), len(lap["tyre_wear"])); self.history_tyre_curves[i].setData(lap["distance"][:nt], lap["tyre_wear"][:nt]); self.history_tyre_curves[i].setPen(pg.mkPen((255, 0, 255, alpha), width=1)); self.history_tyre_curves[i].show()
                if self.show_ers and lap["ers_store"]:
                    ne = min(len(lap["distance"]), len(lap["ers_store"])); self.history_ers_curves[i].setData(lap["distance"][:ne], lap["ers_store"][:ne]); self.history_ers_curves[i].setPen(pg.mkPen((0, 0, 255, alpha), width=1)); self.history_ers_curves[i].show()

            # Update shared marker
            marker_dist = self.telemetry_data.marker_dist
            if marker_dist is not None:
                for line in self.marker_lines:
                    line.setValue(marker_dist)
                    line.show()
            else:
                for line in self.marker_lines: line.hide()
