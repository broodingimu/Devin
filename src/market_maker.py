"""
Market maker module for coordinating price manipulation through distributed trades.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Union

from .wallet_manager import WalletManager
from .raydium_interface import RaydiumInterface
from .pump_fun_interface import PumpFunInterface
from .trade_distributor import TradeDistributor
from .csv_processor import CSVProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MarketMaker:
    def __init__(
        self,
        address: str,
        csv_path: str,
        dex_name: str = "raydium",
        interval_minutes: int = 5,
        max_slippage: float = 0.01,
        min_trade_size: float = 0.1,
        max_trade_size: float = 1.0,
        max_trades_per_interval: int = 5,
        price_check_interval: int = 10  # seconds between price checks
    ):
        """
        Initialize market maker.
        
        Args: 
            address: DEX-specific address (pool address for Raydium, mint address for pump.fun)
            dex_name: Name of DEX to use ("raydium" or "pump_fun")
            csv_path: Path to CSV file with target prices
            interval_minutes: Time interval between price targets
            max_slippage: Maximum acceptable slippage per trade
            min_trade_size: Minimum trade size in SOL
            max_trade_size: Maximum trade size in SOL
            max_trades_per_interval: Maximum trades per interval
            price_check_interval: Seconds between price checks
        """
        self.wallet_manager = WalletManager()
        
        # Initialize DEX interface based on dex_name
        if dex_name == "raydium":
            self.dex_interface = RaydiumInterface(address)
        elif dex_name == "pump_fun":
            self.dex_interface = PumpFunInterface(address)
        else:
            raise ValueError(f"Unsupported DEX: {dex_name}")
            
        self.trade_distributor = TradeDistributor(
            wallet_manager=self.wallet_manager,
            dex_interface=self.dex_interface,
            min_trade_size=min_trade_size,
            max_trade_size=max_trade_size,
            max_trades_per_interval=max_trades_per_interval
        )
        self.csv_processor = CSVProcessor(csv_path, interval_minutes)
        self.max_slippage = max_slippage
        self.price_check_interval = price_check_interval
        self.running = False
        self.last_error = None

    async def start(self):
        """Start the market maker."""
        try:
            # Load price targets
            self.csv_processor.load_price_data()
            logger.info("Loaded price targets from CSV")
            
            self.running = True
            await self._run_price_manipulation()
            
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Market maker failed to start: {e}")
            raise
        finally:
            await self.cleanup()

    async def stop(self):
        """Stop the market maker."""
        self.running = False
        logger.info("Market maker stopped")
        await self.cleanup()

    async def _run_price_manipulation(self):
        """Run the main price manipulation loop."""
        while self.running:
            try:
                remaining = self.csv_processor.get_remaining_targets()
                if remaining <= 0:
                    logger.info("No more price targets remaining")
                    self.running = False
                    return  # Exit immediately when no targets remain
                # Get next target price
                target_price, target_time = await self.csv_processor.get_next_target()
                if target_price is None:
                    # Not time for next target yet
                    await asyncio.sleep(self.price_check_interval)
                    continue

                # Get current price
                current_price = await self.dex_interface.get_pool_price()
                logger.info(
                    f"Current price: {current_price:.4f}, "
                    f"Target price: {target_price:.4f}"
                )

                # Skip if price is already at target (within 0.1%)
                if abs(current_price - target_price) / current_price < 0.001:
                    logger.info("Current price already matches target")
                    continue

                # Calculate and execute trades
                trades = await self.trade_distributor.calculate_trade_distribution(
                    target_price=target_price,
                    current_price=current_price,
                    max_slippage=self.max_slippage
                )

                if trades:
                    signatures = await self.trade_distributor.execute_trades(
                        trades=trades,
                        max_slippage=self.max_slippage
                    )
                    
                    # Log trade results
                    successful_trades = len(signatures)
                    total_trades = len(trades)
                    if successful_trades < total_trades:
                        logger.warning(
                            f"Only {successful_trades}/{total_trades} trades succeeded"
                        )
                    else:
                        logger.info(f"Successfully executed {successful_trades} trades")
                        
                    # Verify price movement
                    new_price = await self.dex_interface.get_pool_price()
                    price_change = (new_price - current_price) / current_price
                    logger.info(
                        f"Price moved from {current_price:.4f} to {new_price:.4f} "
                        f"({price_change:.2%} change)"
                    )
                else:
                    logger.info("No trades needed for current target")

            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Error in price manipulation loop: {e}")
                self.running = False  # Stop on error
                return  # Exit immediately on error

    async def cleanup(self):
        """Clean up resources."""
        if hasattr(self, '_cleaned_up'):
            return
        try:
            await self.wallet_manager.close()
            await self.dex_interface.close()
            logger.info("Cleaned up resources")
            self._cleaned_up = True
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    required_env = ["DEX_ADDRESS", "DEX_NAME", "PRICE_CSV_PATH"]
    missing_env = [var for var in required_env if not os.getenv(var)]
    if missing_env:
        raise ValueError(f"Missing required environment variables: {missing_env}")
    
    bot = MarketMaker(
        address=os.getenv("DEX_ADDRESS"),
        dex_name=os.getenv("DEX_NAME", "raydium").lower(),
        csv_path=os.getenv("PRICE_CSV_PATH"),
        max_slippage=float(os.getenv("MAX_SLIPPAGE", "0.01")),
        min_trade_size=float(os.getenv("MIN_TRADE_SIZE", "0.1")),
        max_trade_size=float(os.getenv("MAX_TRADE_SIZE", "1.0")),
        max_trades_per_interval=int(os.getenv("MAX_TRADES_PER_INTERVAL", "5"))
    )
    
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt: 
        logger.info("Shutting down market maker...")
        asyncio.run(bot.stop())
