import sys
import argparse
from PyQt5 import QtWidgets

from data_manager import TelemetryData
from listener import TelemetryListener
from plotter import PlotterWindow

# Configuration
DEFAULT_UDP_PORT = 20778

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
