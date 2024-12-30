"""
Trade distribution module for market making bot.
Handles distributing trades across multiple wallets.
"""
from typing import List, Dict, Optional, Tuple
import logging
import random
from datetime import datetime, timedelta
from solders.keypair import Keypair

from .wallet_manager import WalletManager
from .raydium_interface import RaydiumInterface

logger = logging.getLogger(__name__)

class TradeDistributor:
    def __init__(
        self,
        wallet_manager: WalletManager,
        raydium: RaydiumInterface,
        min_trade_size: float = 0.1,  # Minimum trade size in SOL
        max_trade_size: float = 1.0,  # Maximum trade size in SOL
        max_trades_per_interval: int = 5  # Maximum trades per 5-min interval
    ):
        """
        Initialize trade distributor.
        
        Args:
            wallet_manager: Wallet manager instance
            raydium: Raydium interface instance
            min_trade_size: Minimum trade size in SOL
            max_trade_size: Maximum trade size in SOL
            max_trades_per_interval: Maximum trades per interval
        """
        self.wallet_manager = wallet_manager
        self.raydium = raydium
        self.min_trade_size = min_trade_size
        self.max_trade_size = max_trade_size
        self.max_trades_per_interval = max_trades_per_interval

    async def calculate_trade_distribution(
        self,
        target_price: float,
        current_price: float,
        max_slippage: float = 0.01
    ) -> List[Tuple[Keypair, float, bool]]:
        """
        Calculate optimal trade distribution across wallets.
        
        Args:
            target_price: Target price to achieve
            current_price: Current market price
            max_slippage: Maximum acceptable slippage per trade
            
        Returns:
            List[Tuple[Keypair, float, bool]]: List of (wallet, amount, is_buy)
        """
        try:
            # Get required total amount
            total_amount = await self.raydium.calculate_required_amount(
                target_price, current_price
            )
            
            if total_amount == 0:
                logger.info("No trades needed - current price matches target")
                return []
            
            # Determine trade direction
            is_buy = target_price > current_price
            
            # Get available wallets with sufficient balance
            min_balance = self.min_trade_size * 1.1  # Add 10% buffer
            available_wallets = await self.wallet_manager.get_available_wallets(
                min_balance
            )
            
            if not available_wallets:
                raise ValueError("No wallets available with sufficient balance")
            
            # Calculate number of trades
            num_trades = min(
                len(available_wallets),
                self.max_trades_per_interval,
                int(total_amount / self.min_trade_size) + 1
            )
            
            # Distribute amount across trades
            base_amount = total_amount / num_trades
            if base_amount > self.max_trade_size: 
                num_trades = int(total_amount / self.max_trade_size) + 1
                base_amount = total_amount / num_trades
            
            # Randomize trade sizes slightly (±10%)
            trades = []
            remaining_amount = total_amount
            selected_wallets = random.sample(available_wallets, num_trades)
            
            for i, wallet in enumerate(selected_wallets):
                if i == len(selected_wallets) - 1:
                    # Last trade - use remaining amount
                    amount = remaining_amount
                else:
                    # Randomize amount ±10%
                    variation = random.uniform(0.9, 1.1)
                    amount = min(
                        base_amount * variation,
                        remaining_amount
                    )
                
                # Ensure amount is within limits
                amount = max(self.min_trade_size, 
                           min(amount, self.max_trade_size))
                
                trades.append((wallet, amount, is_buy))
                remaining_amount -= amount
            
            logger.info(
                f"Distributed {total_amount:.4f} SOL across {len(trades)} trades"
            )
            return trades
            
        except Exception as e:
            logger.error(f"Error calculating trade distribution: {str(e)}")
            raise

    async def execute_trades(
        self,
        trades: List[Tuple[Keypair, float, bool]],
        max_slippage: float = 0.01
    ) -> List[str]:
        """
        Execute distributed trades.
        
        Args:
            trades: List of (wallet, amount, is_buy) tuples
            max_slippage: Maximum acceptable slippage per trade
            
        Returns:
            List[str]: List of transaction signatures
        """
        signatures = []
        
        for wallet, amount, is_buy in trades:
            try:
                # Use wallet's execute_trade if available (for testing), otherwise use Raydium
                if hasattr(wallet, 'execute_trade'):
                    signature = await wallet.execute_trade(amount, is_buy)
                else:
                    signature = await self.raydium.execute_market_order(
                        wallet=wallet,
                        amount=amount,
                        is_buy=is_buy,
                        max_slippage=max_slippage
                    )
                signatures.append(signature)
                
                # Record transaction
                self.wallet_manager.record_transaction(
                    str(wallet.pubkey()),
                    "BUY" if is_buy else "SELL",
                    amount
                )
                
            except Exception as e:
                logger.error(
                    f"Trade failed for wallet {wallet.pubkey()}: {str(e)}"
                )
                continue
        
        return signatures
