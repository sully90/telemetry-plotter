# SimHub Real-Time Telemetry Plotter

A Python-based real-time telemetry plotter for SimHub. It displays speed, throttle, and brake data lap-by-lap, maintaining a history of previous laps with a fading effect.

## Features
- **Real-time Plotting**: High-performance visualization using `pyqtgraph`.
- **Lap-by-Lap History**: Automatically detects new laps and stores the previous ones.
- **Configurable History**: Control how many previous laps are displayed.
- **Fading Effect**: Older laps gradually fade out, making it easy to compare your current performance against recent ones.
- **Cross-Sim Support**: Works with any game supported by SimHub (F1 24, Assetto Corsa, etc.).

## Prerequisites
1. **SimHub**: Must be installed and running.
2. **SimHub Web Server**: Ensure the Web Server is enabled in SimHub settings (default port 8888).
3. **Python 3.7+**: Make sure Python is installed on your system.

## Installation

1. Navigate to the project directory:
   ```bash
   cd telemetry_plotter
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the application:
```bash
python main.py
```

### Configuration Options
You can configure the number of laps to maintain using the `--laps` argument:
```bash
python main.py --laps 10
```

If your SimHub is running on a different machine or port, use the `--url` argument:
```bash
python main.py --url ws://192.168.1.10:8888/ws
```

## How it works
The application connects to the SimHub WebSocket API to receive live telemetry updates. It uses `PyQtGraph` for efficient real-time plotting, which is much faster than standard Matplotlib for high-frequency data. 

The X-axis is based on `DistanceRoundTrack`, allowing for perfect alignment of telemetry across different laps regardless of time variations.
