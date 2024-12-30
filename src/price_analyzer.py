"""
Price analysis module for market making bot.
Handles price monitoring and impact calculations.
"""
from typing import Tuple
from .raydium_interface import RaydiumInterface

class PriceAnalyzer:
    def __init__(self, raydium: RaydiumInterface):
        self.raydium = raydium

    async def analyze_price_movement(self, current_price: float, target_price: float) -> Tuple[float, int]:
        """
        Analyze required price movement and suggest number of trades.
        Returns (total_amount_needed, suggested_num_trades)
        """
        price_diff = abs(target_price - current_price)
        is_buy = target_price > current_price
        
        # Calculate total amount needed
        amount_needed = await self.raydium.calculate_required_amount(
            target_price, current_price
        )
        
        # Suggest number of trades based on price impact
        impact_threshold = 0.005  # 0.5% max impact per trade
        _, impact = await self.raydium.estimate_price_impact(amount_needed, is_buy)
        num_trades = max(1, int(impact / impact_threshold))
        
        return amount_needed, num_trades
