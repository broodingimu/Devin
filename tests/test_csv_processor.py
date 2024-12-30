"""
Unit tests for CSV processor module.
"""
import pytest
from datetime import datetime, timedelta
import pandas as pd
import tempfile
import os

from src.csv_processor import CSVProcessor

@pytest.fixture
def sample_csv(request):
    """Create a temporary CSV file with sample data."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
        f.write("timestamp,target_price\n")
        base_time = datetime.now().replace(microsecond=0)
        
        # Write 10 price targets at 5-minute intervals
        for i in range(10):
            timestamp = base_time + timedelta(minutes=5*i)
            price = 1.0 + (i * 0.1)  # Increasing prices
            f.write(f"{timestamp.isoformat()},{price:.2f}\n")
        
        temp_path = f.name
    
    def cleanup():
        try:
            os.unlink(temp_path)
        except OSError: 
            pass
    
    request.addfinalizer(cleanup)
    return temp_path

def test_load_price_data(sample_csv):
    """Test loading price data from CSV."""
    processor = CSVProcessor(sample_csv)
    df = processor.load_price_data()
    
    assert len(df) == 10
    assert all(df.columns == ['timestamp', 'target_price'])
    assert all(df['target_price'] > 0)
    
    # Check intervals
    time_diffs = df['timestamp'].diff()[1:]
    assert all(diff == timedelta(minutes=5) for diff in time_diffs)

@pytest.mark.asyncio
async def test_get_next_target(sample_csv):
    """Test getting next target price."""
    processor = CSVProcessor(sample_csv)
    processor.load_price_data()
    
    # First target
    price, timestamp = await processor.get_next_target()
    assert price is not None
    assert isinstance(timestamp, datetime)
    
    # Should return None if called too soon
    price, timestamp = await processor.get_next_target()
    assert price is None
    assert timestamp is None
    
    # Wait for interval
    processor.last_update -= timedelta(minutes=5)
    price, timestamp = await processor.get_next_target()
    assert price is not None
    assert isinstance(timestamp, datetime)

@pytest.mark.asyncio
async def test_get_remaining_targets(sample_csv):
    """Test getting remaining target count."""
    processor = CSVProcessor(sample_csv)
    
    # Before loading
    assert processor.get_remaining_targets() == 0
    
    processor.load_price_data()
    assert processor.get_remaining_targets() == 10
    
    # After getting some targets
    await processor.get_next_target()
    assert processor.get_remaining_targets() == 9

@pytest.mark.asyncio
async def test_reset(sample_csv):
    """Test resetting processor state."""
    processor = CSVProcessor(sample_csv)
    processor.load_price_data()
    
    # Get some targets
    await processor.get_next_target()
    await processor.get_next_target()
    assert processor.get_remaining_targets() < 10
    
    # Reset
    processor.reset()
    assert processor.get_remaining_targets() == 10
    assert processor.current_index == 0
    assert processor.last_update is None

def test_invalid_csv():
    """Test handling invalid CSV files."""
    # Missing required columns
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
        f.write("time,price\n1.0,2.0\n")
        invalid_csv = f.name
    
    try:
        processor = CSVProcessor(invalid_csv)
        with pytest.raises(ValueError, match="CSV must contain columns"):
            processor.load_price_data()
    finally:
        os.unlink(invalid_csv)
    
    # Invalid prices
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
        f.write("timestamp,target_price\n2024-01-01 00:00:00,-1.0\n")
        invalid_csv = f.name
    
    try:
        processor = CSVProcessor(invalid_csv)
        with pytest.raises(ValueError, match="All target prices must be positive"):
            processor.load_price_data()
    finally:
        if invalid_csv:
            try:
                os.unlink(invalid_csv)
            except OSError:
                pass
