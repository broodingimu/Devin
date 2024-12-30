"""
Pump.fun DEX interface for market making bot.
Handles interactions with bonding curve and trade execution.
"""
from typing import Tuple, Dict, Optional
import asyncio
import logging
from decimal import Decimal
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey
from solders.hash import Hash

from .pump_fun.bonding_curve_account import (
    BondingCurveAccount,
    get_bonding_curve_account,
    derive_bonding_curve_accounts
)
from .pump_fun.pump_fun import (
    get_buy_instructions,
    get_sell_instructions
)
from .pump_fun.constants import (
    SOL_DECIMAL,
    TOKEN_DECIMAL,
    PUMP_FUN_PROGRAM
)

logger = logging.getLogger(__name__)

class PumpFunInterface:
    def __init__(self, mint_address: str, rpc_url: Optional[str] = None):
        """
        Initialize Pump.fun interface.
        
        Args:
            mint_address: Token mint address
            rpc_url: Optional Solana RPC URL
        """
        self.client = AsyncClient(rpc_url)
        self.mint = Pubkey.from_string(mint_address)
        self.bonding_curve_data: Optional[BondingCurveAccount] = None
        self.last_update = 0
        self.update_interval = 1  # Update bonding curve data every second
        
    async def _fetch_bonding_curve_data(self) -> BondingCurveAccount:
        """Fetch current bonding curve state."""
        try:
            bonding_curve_data = await get_bonding_curve_account(
                self.client,
                self.mint
            )
            if not bonding_curve_data:
                raise ValueError(f"Bonding curve for mint {self.mint} not found")
                
            self.bonding_curve_data = bonding_curve_data
            self.last_update = asyncio.get_event_loop().time()
            return bonding_curve_data
            
        except Exception as e:
            logger.error(f"Error fetching bonding curve data: {str(e)}")
            raise
            
    async def get_pool_price(self) -> float:
        """
        Get current price from the bonding curve.
        
        Returns:
            float: Current token price in SOL
        """
        current_time = asyncio.get_event_loop().time()
        if not self.bonding_curve_data or current_time - self.last_update > self.update_interval:
            await self._fetch_bonding_curve_data()
            
        if not self.bonding_curve_data:  # If still no data after fetch
            raise ValueError("Bonding curve data not available")
            
        return self.bonding_curve_data.get_token_price()

    async def estimate_price_impact(
        self, 
        amount: float, 
        is_buy: bool
    ) -> Tuple[float, float]:
        """
        Estimate price impact and slippage for a given trade amount.
        
        Args:
            amount: Trade amount in SOL
            is_buy: True for buy, False for sell
            
        Returns:
            Tuple[float, float]: (expected_price, price_impact)
        """
        await self._fetch_bonding_curve_data()
        
        if not self.bonding_curve_data:
            raise ValueError("Bonding curve data not available")
        
        amount_lamports = int(amount * 10**SOL_DECIMAL)
        
        if is_buy:
            tokens_out = self.bonding_curve_data.get_buy_amount_out(amount_lamports)
            new_price = (self.bonding_curve_data.virtual_sol_reserves + amount_lamports) / \
                       (self.bonding_curve_data.virtual_token_reserves - tokens_out)
        else:
            sol_out = self.bonding_curve_data.get_sell_amount_out(amount_lamports)
            new_price = (self.bonding_curve_data.virtual_sol_reserves - sol_out) / \
                       (self.bonding_curve_data.virtual_token_reserves + amount_lamports)
            
        current_price = self.bonding_curve_data.get_token_price()
        price_impact = abs(new_price - current_price) / current_price
        
        return new_price, price_impact

    async def calculate_required_amount(
        self, 
        target_price: float, 
        current_price: float
    ) -> float:
        """
        Calculate required SOL amount to move price to target.
        
        Args:
            target_price: Target token price
            current_price: Current token price
            
        Returns:
            float: Required amount of SOL
        """
        await self._fetch_bonding_curve_data()
        
        if not self.bonding_curve_data:
            raise ValueError("Bonding curve data not available")
            
        virtual_token_reserves = self.bonding_curve_data.virtual_token_reserves
        virtual_sol_reserves = self.bonding_curve_data.virtual_sol_reserves
        
        if target_price > current_price:
            # Need to buy tokens
            # Solve: (virtual_sol_reserves + x) / (virtual_token_reserves - y) = target_price
            # where y is the amount of tokens we get for x SOL
            required_sol = virtual_sol_reserves * (
                (target_price / current_price) ** 0.5 - 1
            )
        else:
            # Need to sell tokens
            # Solve: (virtual_sol_reserves - y) / (virtual_token_reserves + x) = target_price
            # where y is the amount of SOL we get for x tokens
            required_sol = virtual_sol_reserves * (
                1 - (target_price / current_price) ** 0.5
            )
            
        return abs(required_sol / 10**SOL_DECIMAL)

    async def execute_market_order(
        self, 
        wallet: Keypair, 
        amount: float, 
        is_buy: bool,
        max_slippage: float = 0.01,  # 1% max slippage
        max_retries: int = 3,
        retry_delay: float = 1.0  # seconds
    ) -> str:
        """
        Execute a market order on Pump.fun with retry mechanism.
        
        Args:
            wallet: Wallet keypair for transaction
            amount: Trade amount in SOL
            is_buy: True for buy, False for sell
            max_slippage: Maximum acceptable slippage
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        
        Returns:
            str: Transaction signature
            
        Raises:
            ValueError: If price impact exceeds slippage or bonding curve state is invalid
            RuntimeError: If transaction fails after all retries
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Get current bonding curve state
                await self._fetch_bonding_curve_data()
                
                if not self.bonding_curve_data:
                    raise ValueError("Invalid bonding curve state")
                
                # Estimate price impact
                expected_price, price_impact = await self.estimate_price_impact(
                    amount, is_buy
                )
                
                if price_impact > max_slippage:
                    raise ValueError(
                        f"Price impact {price_impact:.2%} exceeds max slippage "
                        f"{max_slippage:.2%}"
                    )
                
                # Get bonding curve accounts
                bonding_curve, associated_bonding_curve = derive_bonding_curve_accounts(
                    self.mint, PUMP_FUN_PROGRAM
                )
                
                # Create instructions
                amount_lamports = int(amount * 10**SOL_DECIMAL)
                instructions = []
                
                if is_buy:
                    # Calculate max SOL cost with slippage
                    max_sol_cost = int(amount_lamports * (1 + max_slippage))
                    instructions.extend(
                        await get_buy_instructions(
                            self.client,
                            self.mint,
                            wallet.pubkey(),
                            bonding_curve,
                            associated_bonding_curve,
                            amount_lamports,
                            max_sol_cost,
                            200000,  # Default compute budget
                            1  # Default priority fee
                        )
                    )
                else:
                    # Calculate min SOL output with slippage
                    min_sol_output = int(amount_lamports * (1 - max_slippage))
                    instructions.extend(
                        await get_sell_instructions(
                            self.client,
                            self.mint,
                            wallet.pubkey(),
                            bonding_curve,
                            associated_bonding_curve,
                            amount_lamports,
                            min_sol_output,
                            200000,  # Default compute budget
                            1  # Default priority fee
                        )
                    )
                
                # Get recent blockhash
                blockhash = await self.client.get_latest_blockhash()
                if not blockhash or 'result' not in blockhash:
                    raise RuntimeError("Failed to get recent blockhash")

                # Convert blockhash string to Hash object
                blockhash_bytes = bytes.fromhex(blockhash['result']['value']['blockhash'])
                blockhash_hash = Hash(blockhash_bytes)

                # Create and sign transaction
                transaction = Transaction.new_with_payer(
                    instructions,
                    wallet.pubkey()
                )
                transaction.sign([wallet], blockhash_hash)
                
                # Send with confirmation
                signature = await self.client.send_transaction(
                    transaction,
                    wallet,
                    opts={
                        "skip_confirmation": False,
                        "max_retries": 3,  # Additional RPC-level retries
                        "preflight_commitment": "confirmed"
                    }
                )
                
                # Verify transaction success
                confirm_result = await self.client.confirm_transaction(
                    signature['result'],
                    commitment="confirmed"
                )
                
                if not confirm_result.get('result', {}).get('value', False):
                    raise RuntimeError("Transaction failed confirmation")
                
                logger.info(
                    f"Order executed: {amount:.4f} SOL, "
                    f"Impact: {price_impact:.2%}, "
                    f"Signature: {signature['result']}, "
                    f"Attempt: {attempt + 1}/{max_retries}"
                )
                
                return signature['result']
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Order attempt {attempt + 1}/{max_retries} failed: {str(e)}"
                )
                
                
                if attempt < max_retries - 1:
                    # Check if error is retryable
                    if isinstance(e, (ValueError, RuntimeError)):
                        # Don't retry validation errors
                        raise
                    
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    # Increase delay for each retry
                    continue
                    
                break
        
        # If we get here, all retries failed
        logger.error(f"Order failed after {max_retries} attempts")
        raise RuntimeError(f"Order execution failed: {str(last_error)}")

    async def close(self):
        """Clean up resources."""
        await self.client.close()
