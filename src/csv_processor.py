"""
CSV processor module for market making bot.
Handles reading and processing target price series from CSV files.
"""
from typing import List, Dict, Optional, Tuple
import logging
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)

class CSVProcessor:
    def __init__(self, csv_path: str, interval_minutes: int = 5):
        """
        Initialize CSV processor.
        
        Args:
            csv_path: Path to CSV file with target prices
            interval_minutes: Time interval between price targets
        """
        self.csv_path = csv_path
        self.interval_minutes = interval_minutes
        self.price_data = None
        self.current_index = 0
        self.last_update = None

    def load_price_data(self) -> pd.DataFrame:
        """
        Load and validate target price series from CSV.
        
        Expected CSV format:
        timestamp,target_price
        2024-02-01 00:00:00,1.23
        2024-02-01 00:05:00,1.25
        ...
        
        Returns:
            pd.DataFrame: Loaded and validated price data
        """
        try:
            # Read CSV file
            df = pd.read_csv(self.csv_path)
            
            # Validate columns
            required_columns = ['timestamp', 'target_price']
            if not all(col in df.columns for col in required_columns):
                raise ValueError(
                    f"CSV must contain columns: {', '.join(required_columns)}"
                )
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Sort by timestamp
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # Validate intervals
            time_diffs = df['timestamp'].diff()[1:]
            expected_diff = timedelta(minutes=self.interval_minutes)
            if not all(abs(diff - expected_diff) < timedelta(seconds=1) 
                      for diff in time_diffs):
                logger.warning(
                    f"Some intervals in CSV do not match {self.interval_minutes} minutes"
                )
            
            # Validate price values
            if not all(df['target_price'] > 0):
                raise ValueError("All target prices must be positive")
            
            self.price_data = df
            self.current_index = 0
            self.last_update = None
            
            logger.info(
                f"Loaded {len(df)} price targets from {self.csv_path}"
            )
            return df
            
        except Exception as e:
            logger.error(f"Error loading CSV: {str(e)}")
            raise

    async def get_next_target(self) -> Tuple[Optional[float], Optional[datetime]]:
        """
        Get next target price and its timestamp from series.
        
        Returns:
            Tuple[Optional[float], Optional[datetime]]: (target_price, target_timestamp)
            Returns (None, None) if no more targets available or not time yet
        """
        if self.price_data is None or self.current_index >= len(self.price_data):
            return None, None
            
        current_time = datetime.now()
        row = self.price_data.iloc[self.current_index]
        
        # Check if it's time for the next target
        if self.last_update:
            time_since_last = current_time - self.last_update
            if time_since_last < timedelta(minutes=self.interval_minutes):
                return None, None
        
        target_price = float(row['target_price'])
        target_time = row['timestamp'].to_pydatetime()
        
        self.current_index += 1
        self.last_update = current_time
        
        return target_price, target_time

    def get_remaining_targets(self) -> int:
        """
        Get number of remaining price targets.
        
        Returns:
            int: Number of remaining targets
        """
        if self.price_data is None:
            return 0
        return max(0, len(self.price_data) - self.current_index)

    def reset(self):
        """Reset processor to start of price series."""
        self.current_index = 0
        self.last_update = None
