import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

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
