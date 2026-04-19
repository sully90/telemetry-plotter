import pytest
from unittest.mock import MagicMock
from telemetry.data_manager import TelemetryData

@pytest.fixture
def telemetry_data():
    # Mock TelemetryRecorder to avoid file IO
    data = TelemetryData()
    data.recorder = MagicMock()
    return data

def test_initialization(telemetry_data):
    assert telemetry_data.player_idx == 0
    assert telemetry_data.track_name == "F1 25 Session"
    assert len(telemetry_data.all_cars_data) == 22
    assert telemetry_data.current_lap_num == -1

def test_update_session(telemetry_data):
    telemetry_data.update_session(0, 15, 1) # Melbourne, Race, Player 1
    assert telemetry_data.track_name == "Melbourne"
    assert telemetry_data.session_type == 15
    assert telemetry_data.player_idx == 1
    assert telemetry_data.current_lap_data == telemetry_data.all_cars_data[1]

def test_update_motion_speed_calculation(telemetry_data):
    car_idx = 0
    # First update to set initial position
    telemetry_data.update_motion(car_idx, 0, 0, 0, 0, 0, 0, 10.0, 1)
    
    # Second update 1 second later, 10 meters away
    # speed = 10 m / 1 s = 10 m/s = 22.3694 mph
    telemetry_data.update_motion(car_idx, 10, 0, 0, 0, 0, 0, 11.0, 2)
    
    latch = telemetry_data.car_latches[car_idx]
    assert pytest.approx(latch["speed_mph"], 0.0001) == 22.3694

def test_lap_completion(telemetry_data):
    telemetry_data.update_session(0, 10, 0) # Melbourne, TT, Player 0
    car_idx = 0
    
    # Simulate some data points for a lap
    for i in range(1, 103):
        telemetry_data.update_lap(car_idx, 1, float(i), i * 1000, float(i), i)
        telemetry_data.update_motion(car_idx, i, 0, 0, 0, 0, 0, float(i) + 0.1, i+1)
    
    # Complete the lap
    telemetry_data.update_lap(car_idx, 2, 0.0, 103000, 103.0, 103)
    
    # Check if history is updated
    assert len(telemetry_data.car_histories[car_idx]) == 1
    assert telemetry_data.best_lap_time != float('inf')
    assert telemetry_data.current_lap_num == 2

def test_flashback_reset(telemetry_data):
    car_idx = 0
    telemetry_data.update_lap(car_idx, 2, 1000.0, 50000, 50.0, 50)
    telemetry_data.update_motion(car_idx, 100, 0, 0, 0, 0, 0, 50.0, 50)
    assert len(telemetry_data.all_cars_data[car_idx]["distance"]) > 0
    
    # Simulate flashback (lap number decreases or distance jumps back)
    telemetry_data.update_lap(car_idx, 1, 500.0, 25000, 60.0, 60)
    
    assert len(telemetry_data.all_cars_data[car_idx]["distance"]) == 0
