import sys
import argparse
from PyQt5 import QtWidgets

from data_manager import TelemetryData
from listener import TelemetryListener
from plotter import PlotterWindow, TrackMapWindow

# Configuration
DEFAULT_UDP_PORT = 20778

def main():
    parser = argparse.ArgumentParser(description="F1 25 Real-Time Telemetry Plotter")
    parser.add_argument("--laps", type=int, default=5, help="Number of previous laps to show")
    parser.add_argument("--port", type=int, default=DEFAULT_UDP_PORT, help="UDP Listening Port")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    
    telemetry_data = TelemetryData(max_laps=args.laps)
    
    listener = TelemetryListener(args.port)
    # Signal Connections
    listener.session_received.connect(telemetry_data.update_session)
    listener.participants_received.connect(telemetry_data.update_participants)
    listener.damage_received.connect(telemetry_data.update_damage)
    listener.status_received.connect(telemetry_data.update_status)
    listener.motion_received.connect(telemetry_data.update_motion)
    listener.lap_received.connect(telemetry_data.update_lap)
    listener.telemetry_received.connect(telemetry_data.update_telemetry)
    listener.tt_indices_received.connect(telemetry_data.update_tt_indices)
    listener.start()
    
    # Set up windows on second monitor if available
    screens = app.screens()
    target_screen = screens[1] if len(screens) > 1 else screens[0]
    geom = target_screen.availableGeometry()
    width = geom.width() // 2
    height = geom.height()

    window = PlotterWindow(telemetry_data)
    window.setGeometry(geom.x(), geom.y(), width, height)
    window.show()

    map_window = TrackMapWindow(telemetry_data)
    map_window.setGeometry(geom.x() + width, geom.y(), width, height)
    
    # Connect signals for global key handling
    map_window.request_toggle_tyre_wear.connect(window.toggle_tyre_wear)
    map_window.request_toggle_ers.connect(window.toggle_ers)
    
    # Connect shared marker
    window.marker_clicked.connect(telemetry_data.set_marker)
    map_window.marker_clicked.connect(telemetry_data.set_marker)
    
    # Sync zoom from Telemetry to Map
    window.view_range_changed.connect(map_window.focus_on_distance_range)
    
    map_window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
