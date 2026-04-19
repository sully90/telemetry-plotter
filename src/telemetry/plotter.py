import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from .data_manager import TEAM_COLORS, SESSION_RACE, SESSION_TIME_TRIAL

from datetime import datetime

def take_screenshot():
    """Captures all visible top-level windows and saves them to a single image."""
    app = QtWidgets.QApplication.instance()
    windows = [w for w in app.topLevelWidgets() if w.isVisible() and isinstance(w, QtWidgets.QMainWindow)]
    if not windows:
        return

    # Determine the bounding rectangle of all windows
    min_x = min(w.x() for w in windows)
    min_y = min(w.y() for w in windows)
    max_x = max(w.x() + w.width() for w in windows)
    max_y = max(w.y() + w.height() for w in windows)

    # Create a transparent pixmap covering the whole area
    full_pixmap = QtGui.QPixmap(max_x - min_x, max_y - min_y)
    full_pixmap.fill(QtCore.Qt.black) # Use black background for consistency

    painter = QtGui.QPainter(full_pixmap)
    for w in windows:
        # Render each window at its relative position
        pix = w.grab()
        painter.drawPixmap(w.x() - min_x, w.y() - min_y, pix)
    painter.end()

    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.png"
    if full_pixmap.save(filename):
        print(f"Screenshot saved to {filename}")

class RecordingIndicator(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setStyleSheet("background-color: red; border-radius: 10px;")
        self.hide()
        # Position in top right corner
        self.move(10, 10)

class TrackMapWindow(QtWidgets.QMainWindow):
    request_toggle_tyre_wear = QtCore.pyqtSignal()
    request_toggle_ers = QtCore.pyqtSignal()
    request_reset_telemetry = QtCore.pyqtSignal()
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

        self.rec_indicator = RecordingIndicator(self)
        self.rec_indicator.raise_()

        self.p_map = self.win.addPlot(title="Track Map (X vs Z)")
        self.p_map.setAspectLocked(True)
        self.p_map.showGrid(x=True, y=True)
        
        # Discovery-based Tracking
        self.auto_track = True
        self.track_fitted = False
        self.current_track_name = ""
        self.map_bounds = [float('inf'), float('-inf'), float('inf'), float('-inf')] # min_x, max_x, min_z, max_z
        self.last_car_pos = {} # For performance optimization
        self.p_map.vb.sigRangeChangedManually.connect(self._on_manual_interaction)

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

    def _on_manual_interaction(self):
        self.auto_track = False

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Q:
            QtWidgets.QApplication.instance().quit()
        elif event.key() == QtCore.Qt.Key_S:
            take_screenshot()
        elif event.key() == QtCore.Qt.Key_Space:
            with self.telemetry_data.lock: self.telemetry_data.marker_dist = None
            self.auto_track = True
            self.track_fitted = False
            self._fit_to_bounds() # Snap back to whole track
            self.request_reset_telemetry.emit()
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

    def _fit_to_bounds(self):
        if self.map_bounds[0] != float('inf'):
            x_min, x_max, z_min, z_max = self.map_bounds
            self.p_map.setRange(xRange=(x_min, x_max), yRange=(z_min, z_max), padding=0.1)

    def focus_on_distance_range(self, dist_min, dist_max):
        # Sync zoom from telemetry
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
                            self.auto_track = False 
                            self.p_map.setRange(xRange=(np.min(x_pts), np.max(x_pts)), yRange=(np.min(z_pts), np.max(z_pts)), padding=0.1)
        except Exception as e:
            print(f"Error syncing zoom: {e}")

    def update_plots(self):
        with self.telemetry_data.lock:
            player_idx = self.telemetry_data.player_idx
            rival_idx = self.telemetry_data.rival_car_idx
            is_tt = self.telemetry_data.session_type in SESSION_TIME_TRIAL
            is_recording = self.telemetry_data.is_recording
            track_name = self.telemetry_data.track_name
            
            # Reset discovery if track changes
            if self.current_track_name != track_name:
                self.map_bounds = [float('inf'), float('-inf'), float('inf'), float('-inf')]
                self.last_car_pos = {}
            self.current_track_name = track_name

            self.rec_indicator.setVisible(is_recording)
            spots = []
            player_pos = None
            for i in range(22):
                latch = self.telemetry_data.car_latches[i]
                if latch["world_x"] is not None:
                    # Discover track bounds based on car movement (ignore 0,0 teleport spikes)
                    if abs(latch["world_x"]) > 1.0 or abs(latch["world_z"]) > 1.0:
                        self.map_bounds[0] = min(self.map_bounds[0], latch["world_x"])
                        self.map_bounds[1] = max(self.map_bounds[1], latch["world_x"])
                        self.map_bounds[2] = min(self.map_bounds[2], latch["world_z"])
                        self.map_bounds[3] = max(self.map_bounds[3], latch["world_z"])

                    team_id = self.telemetry_data.all_cars_team_ids[i]
                    color = TEAM_COLORS.get(team_id, (200, 200, 200))
                    if i == player_idx: 
                        color = (255, 255, 255); size = 12; symbol = 't'
                        player_pos = (latch["world_x"], latch["world_z"])
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
                n = len(car_data["pos_x"])
                if n > 0:
                    # Skip update if no new data points
                    if i in self.last_car_pos and self.last_car_pos[i] == n:
                        continue
                    self.last_car_pos[i] = n

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
            n_player = len(player_data["pos_x"])
            if n_player > 0:
                # Skip update if no new data
                if player_idx not in self.last_car_pos or self.last_car_pos[player_idx] != n_player:
                    self.curr_curve.setData(player_data["pos_x"], player_data["pos_z"])
                    self.last_car_pos[player_idx] = n_player
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
                self.auto_track = False
                if player_data["distance"]:
                    mx = np.interp(marker_dist, player_data["distance"], player_data["pos_x"])
                    mz = np.interp(marker_dist, player_data["distance"], player_data["pos_z"])
                    self.marker_point.setData([{'pos': (mx, mz)}])
                    self.marker_point.show()
                else: self.marker_point.hide()
            else:
                self.marker_point.hide()
                # Fit view to discovered track if auto-tracking is enabled
                if self.auto_track:
                    self._fit_to_bounds()

class SteeringWheelWindow(QtWidgets.QMainWindow):
    def __init__(self, telemetry_data):
        super().__init__()
        self.telemetry_data = telemetry_data
        self.setWindowTitle("F1 25 Steering")
        self.resize(300, 300)
        self.setStyleSheet("background-color: black;")

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)
        self.win = pg.GraphicsLayoutWidget(show=True)
        layout.addWidget(self.win)

        self.vb = self.win.addViewBox(lockAspect=True, enableMenu=False, enableMouse=False)
        self.vb.setRange(xRange=(-50, 50), yRange=(-50, 50))

        # Create F1 Steering Wheel Path
        path = QtGui.QPainterPath()
        path.addRoundedRect(-25, -15, 50, 30, 5, 5) # Central body
        path.addRoundedRect(-30, -20, 15, 40, 5, 5) # Left grip
        path.addRect(15, -20, 15, 40)  # Right grip (fixed: rect for F1 grips)
        # Fix path to be symmetric and butterfly like
        path = QtGui.QPainterPath()
        path.addRoundedRect(-20, -10, 40, 20, 5, 5) # Hub
        path.addRoundedRect(-30, -20, 15, 40, 8, 8) # Left
        path.addRoundedRect(15, -20, 15, 40, 8, 8)  # Right
        
        self.wheel_item = QtWidgets.QGraphicsPathItem(path)
        self.wheel_item.setPen(pg.mkPen('w', width=3))
        self.wheel_item.setBrush(pg.mkBrush(40, 40, 40))
        self.wheel_item.setTransformOriginPoint(0, 0)
        self.vb.addItem(self.wheel_item)
        
        # Red "Top" marker
        top_marker = pg.ArrowItem(angle=-90, tipAngle=60, headLen=15, brush=pg.mkBrush('r'))
        top_marker.setPos(0, -15)
        top_marker.setParentItem(self.wheel_item)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(30) # High refresh for smooth rotation

    def update_plots(self):
        with self.telemetry_data.lock:
            p_idx = self.telemetry_data.player_idx
            steer = self.telemetry_data.car_latches[p_idx].get("steer", 0.0)
            self.wheel_item.setRotation(-steer * 90.0)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Q:
            QtWidgets.QApplication.instance().quit()
        elif event.key() == QtCore.Qt.Key_S:
            take_screenshot()
        super().keyPressEvent(event)

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

        self.rec_indicator = RecordingIndicator(self)
        self.rec_indicator.raise_()

        # Create subplots
        self.p_speed = self.win.addPlot(title="Speed (mph)")
        self.win.nextRow()
        self.p_throttle = self.win.addPlot(title="Pedals (Throttle/Brake %)")
        self.win.nextRow()
        self.p_tyre = self.win.addPlot(title="Max Tyre Wear (%)")
        self.win.nextRow()
        self.p_ers = self.win.addPlot(title="ERS Battery Store (%)")
        self.p_ers.setYRange(0, 100)

        # Link X-axes
        self.p_throttle.setXLink(self.p_speed)
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

        # Current Lap (Solid)
        self.curr_speed_curve = self.p_speed.plot(pen=pg.mkPen('w', width=3)); self.curr_speed_curve.setZValue(100)
        self.curr_throttle_curve = self.p_throttle.plot(pen=pg.mkPen('g', width=3)); self.curr_throttle_curve.setZValue(100)
        self.curr_brake_curve = self.p_throttle.plot(pen=pg.mkPen('r', width=3)); self.curr_brake_curve.setZValue(100)
        self.curr_tyre_curve = self.p_tyre.plot(pen=pg.mkPen('m', width=3)); self.curr_tyre_curve.setZValue(100)
        self.curr_ers_curve = self.p_ers.plot(pen=pg.mkPen('b', width=3)); self.curr_ers_curve.setZValue(100)

        # Shared Marker (Vertical Yellow lines)
        self.marker_lines = []
        for p in [self.p_speed, self.p_throttle, self.p_tyre, self.p_ers]:
            line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('y', width=1, style=QtCore.Qt.DashLine))
            line.setZValue(200)
            p.addItem(line)
            self.marker_lines.append(line)

        # Performance optimization
        self.last_data_lens = {i: 0 for i in range(22)}
        self.pen_cache = {}

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(50)

    def _get_cached_pen(self, color, alpha=255, width=1):
        key = (*color, alpha, width)
        if key not in self.pen_cache:
            self.pen_cache[key] = pg.mkPen((*color, alpha), width=width)
        return self.pen_cache[key]

    def toggle_tyre_wear(self):
        self.show_tyre_wear = not self.show_tyre_wear
        if self.show_tyre_wear: self.p_tyre.show()
        else: self.p_tyre.hide()

    def toggle_ers(self):
        self.show_ers = not self.show_ers
        if self.show_ers: self.p_ers.show()
        else: self.p_ers.hide()

    def reset_zoom(self):
        self.p_speed.enableAutoRange(axis='xy')
        self.p_speed.setAutoVisible(x=True, y=True)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Q:
            QtWidgets.QApplication.instance().quit()
        elif event.key() == QtCore.Qt.Key_S:
            take_screenshot()
        elif event.key() == QtCore.Qt.Key_Space:
            with self.telemetry_data.lock: self.telemetry_data.marker_dist = None
            self.reset_zoom()
        elif event.key() == QtCore.Qt.Key_T:
            self.toggle_tyre_wear()
        elif event.key() == QtCore.Qt.Key_E:
            self.toggle_ers()
        elif event.key() == QtCore.Qt.Key_R:
            self.telemetry_data.toggle_recording()
        super().keyPressEvent(event)

    def _handle_range_change(self, window, view_range):
        # Only sync if not auto-ranging (i.e. user has manually zoomed/panned)
        if not self.p_speed.vb.state['autoRange'][0]:
            self.view_range_changed.emit(view_range[0], view_range[1])

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MidButton:
            try:
                pos = event.pos()
                scene_pos = self.win.mapToScene(pos)
                # Find which plot was clicked
                for p in [self.p_speed, self.p_throttle, self.p_tyre, self.p_ers]:
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
            
            self.rec_indicator.setVisible(is_recording)
            
            track_name = self.telemetry_data.track_name
            mode_str = "RACE MODE" if is_race else "TIME TRIAL" if is_tt else "PRACTICE"
            rec_str = " [RECORDING]" if is_recording else ""
            self.setWindowTitle(f"F1 25 Telemetry - {track_name} [{mode_str}]{rec_str} (T:Tyre, E:Energy, R:Record, Space:Clear)")

            # Update Opponents / Rival Ghost
            for i in range(22):
                car_data = self.telemetry_data.all_cars_data[i]
                n = len(car_data["distance"])
                
                if i == player_idx or n == 0:
                    self.opp_speed_curves[i].hide(); self.opp_throttle_curves[i].hide()
                    self.opp_brake_curves[i].hide(); self.opp_tyre_curves[i].hide(); self.opp_ers_curves[i].hide()
                    if i == rival_idx: 
                        self.rival_speed_curve.hide(); self.rival_throttle_curve.hide(); self.rival_brake_curve.hide()
                    self.last_data_lens[i] = 0
                    continue
                
                # Only update if data has grown (prevents jitter)
                if n == self.last_data_lens[i]:
                    continue
                self.last_data_lens[i] = n
                
                # Special handling for Rival Ghost in TT
                if is_tt and i == rival_idx:
                    ns = min(n, len(car_data["speed"]))
                    self.rival_speed_curve.setData(car_data["distance"][:ns], car_data["speed"][:ns]); self.rival_speed_curve.show()
                    self.rival_throttle_curve.setData(car_data["distance"][:ns], car_data["throttle"][:ns]); self.rival_throttle_curve.show()
                    self.rival_brake_curve.setData(car_data["distance"][:ns], car_data["brake"][:ns]); self.rival_brake_curve.show()
                    self.opp_speed_curves[i].hide() # Don't show faint opponent curve for rival
                elif is_race or (not is_tt and car_data["distance"]):
                    # Show as regular opponent if in race or if we have data in practice
                    team_id = self.telemetry_data.all_cars_team_ids[i]
                    color = TEAM_COLORS.get(team_id, (150, 150, 150))
                    # If it's not a race, make it even fainter
                    alpha = 80 if is_race else 40
                    pen = self._get_cached_pen(color, alpha)
                    
                    ns = min(n, len(car_data["speed"]), len(car_data["throttle"]), len(car_data["brake"]))
                    self.opp_speed_curves[i].setPen(pen); self.opp_speed_curves[i].setData(car_data["distance"][:ns], car_data["speed"][:ns]); self.opp_speed_curves[i].show()
                    self.opp_throttle_curves[i].setPen(pen); self.opp_throttle_curves[i].setData(car_data["distance"][:ns], car_data["throttle"][:ns]); self.opp_throttle_curves[i].show()
                    self.opp_brake_curves[i].setPen(pen); self.opp_brake_curves[i].setData(car_data["distance"][:ns], car_data["brake"][:ns]); self.opp_brake_curves[i].show()
                    if self.show_tyre_wear and car_data["tyre_wear"]:
                        nt = min(n, len(car_data["tyre_wear"]))
                        self.opp_tyre_curves[i].setPen(pen); self.opp_tyre_curves[i].setData(car_data["distance"][:nt], car_data["tyre_wear"][:nt]); self.opp_tyre_curves[i].show()
                    if self.show_ers and car_data["ers_store"]:
                        ne = min(n, len(car_data["ers_store"]))
                        self.opp_ers_curves[i].setPen(pen); self.opp_ers_curves[i].setData(car_data["distance"][:ne], car_data["ers_store"][:ne]); self.opp_ers_curves[i].show()
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

            # Update Current Lap
            current = self.telemetry_data.current_lap_data
            if current["distance"] and current["speed"]:
                n = min(len(current["distance"]), len(current["speed"]), len(current["throttle"]), len(current["brake"]), len(current["time"]))
                curr_dist_raw = np.array(current["distance"][:n]); curr_time_raw = np.array(current["time"][:n])
                
                # Filter out junk/out-lap data (distances < -10m)
                mask = curr_dist_raw > -10
                if not np.any(mask): 
                    return
                
                curr_dist = curr_dist_raw[mask]
                n = len(curr_dist)

                self.curr_speed_curve.setData(curr_dist, np.array(current["speed"][:n+len(curr_dist_raw)-n])[mask])
                self.curr_throttle_curve.setData(curr_dist, np.array(current["throttle"][:n+len(curr_dist_raw)-n])[mask])
                self.curr_brake_curve.setData(curr_dist, np.array(current["brake"][:n+len(curr_dist_raw)-n])[mask])
                
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
