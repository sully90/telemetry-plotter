import os
import pytest
import pandas as pd
from telemetry.recorder import TelemetryRecorder

def test_recorder_flow(tmp_path):
    # Use a temporary directory for recordings
    recorder = TelemetryRecorder(output_dir=str(tmp_path))
    
    # Mock data
    track_name = "Melbourne"
    units = {"speed": "mph"}
    
    recorder.start_recording(track_name, units)
    assert recorder.is_recording
    
    sample = {
        "car_idx": 0,
        "distance": 10.5,
        "speed": 150.0
    }
    recorder.add_sample(sample)
    assert len(recorder.recording_log) == 1
    
    filepath = recorder.stop_recording()
    assert not recorder.is_recording
    assert os.path.exists(filepath)
    assert filepath.endswith(".parquet")
    
    # Verify data can be read back
    df = recorder.read_recording(filepath)
    assert len(df) == 1
    assert df.iloc[0]["car_idx"] == 0
    assert df.iloc[0]["distance"] == 10.5
