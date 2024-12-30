"""
Raydium DEX interface for market making bot.
Handles interactions with liquidity pools and trade execution.
"""
from typing import Tuple, Dict, Optional
import asyncio
import logging
from decimal import Decimal
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.instruction import Instruction as TransactionInstruction, AccountMeta
# TODO: Replace with proper token account derivation once spl-token package is approved
def get_associated_token_address(wallet_pubkey, pool_pubkey):
    """Temporary implementation - returns a derived address for testing"""
    from hashlib import sha256
    from solders.pubkey import Pubkey
    # Convert pubkeys to bytes and concatenate
    seed = bytes(str(wallet_pubkey).encode()) + bytes(str(pool_pubkey).encode())
    # Create a 32-byte array from the hash
    hash_bytes = sha256(seed).digest()
    # Convert to Pubkey
    return Pubkey(list(hash_bytes))

logger = logging.getLogger(__name__)

class RaydiumInterface:
    def __init__(self, pool_address: str, rpc_url: Optional[str] = None):
        """
        Initialize Raydium interface.
        
        Args:
            pool_address: Liquidity pool address
            rpc_url: Optional Solana RPC URL
        """
        from solders.pubkey import Pubkey
        self.client = AsyncClient(rpc_url)
        self.pool_address = Pubkey.from_string(pool_address)
        self.pool_data: Dict = {}
        self.last_update = 0
        self.update_interval = 1  # Update pool data every second
        
    async def _fetch_pool_data(self) -> Dict:
        """Fetch current pool state."""
        try:
            account_info = await self.client.get_account_info(
                self.pool_address,
                commitment=Confirmed
            )
            if not account_info or not account_info['result']['value']:
                raise ValueError(f"Pool {self.pool_address} not found")
                
            data = account_info['result']['value']['data']
            # Parse pool data (token amounts, weights, fees)
            # This is a simplified version - actual implementation needs
            # to decode specific Raydium pool layout
            pool_data = {
                "token_a_amount": int.from_bytes(data[0:8], "little"),
                "token_b_amount": int.from_bytes(data[8:16], "little"),
                "fee_rate": int.from_bytes(data[16:24], "little") / 10000,
            }
            
            self.pool_data = pool_data
            self.last_update = asyncio.get_event_loop().time()
            return pool_data
            
        except Exception as e:
            logger.error(f"Error fetching pool data: {str(e)}")
            raise

    async def get_pool_price(self) -> float:
        """
        Get current price from the liquidity pool.
        
        Returns:
            float: Current token price in SOL
        """
        current_time = asyncio.get_event_loop().time()
        if not self.pool_data or current_time - self.last_update > self.update_interval:
            await self._fetch_pool_data()
            
        if not self.pool_data:  # If still no pool data after fetch
            raise ValueError("Pool data not available")
            
        # Calculate price based on constant product formula
        # price = token_b_amount / token_a_amount
        return (self.pool_data["token_b_amount"] / 
                self.pool_data["token_a_amount"])

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
        await self._fetch_pool_data()
        
        token_a = self.pool_data["token_a_amount"]
        token_b = self.pool_data["token_b_amount"]
        fee_rate = self.pool_data["fee_rate"]
        
        # Calculate amount after fees
        amount_after_fees = amount * (1 - fee_rate)
        
        if is_buy:
            new_token_a = token_a + amount_after_fees
            new_token_b = (token_a * token_b) / new_token_a
        else:
            new_token_a = token_a - amount_after_fees
            new_token_b = (token_a * token_b) / new_token_a
            
        # Calculate prices
        current_price = token_b / token_a
        expected_price = new_token_b / new_token_a
        price_impact = abs(expected_price - current_price) / current_price
        
        return expected_price, price_impact

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
        await self._fetch_pool_data()
        
        token_a = self.pool_data["token_a_amount"]
        token_b = self.pool_data["token_b_amount"]
        
        # Calculate required amount using constant product formula
        # (x + dx)(y - dy) = xy where dx is our required amount
        if target_price > current_price:
            # Need to buy tokens
            dx = token_a * (
                (target_price / current_price) ** 0.5 - 1
            )
        else:
            # Need to sell tokens
            dx = token_a * (
                1 - (target_price / current_price) ** 0.5
            )
            
        # Add extra to account for fees
        fee_adjustment = 1 / (1 - self.pool_data["fee_rate"])
        return abs(dx * fee_adjustment)

    async def execute_market_order(
        self, 
        wallet: Keypair, 
        amount: float, 
        is_buy: bool,
        max_slippage: float = 0.01,  # 1% max slippage
        max_retries: int = 3,
        retry_delay: float = 1.0  # seconds
    ):
        """
        Execute a market order on Raydium with retry mechanism.
        
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
            ValueError: If price impact exceeds slippage or pool state is invalid
            RuntimeError: If transaction fails after all retries
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Get current pool state
                await self._fetch_pool_data()
                
                # Verify pool state
                if not self.pool_data:
                    raise ValueError("Invalid pool state")
                
                # Check if pool has enough liquidity
                min_liquidity = amount * 10  # Pool should have 10x the trade amount
                if self.pool_data["token_a_amount"] < min_liquidity or \
                   self.pool_data["token_b_amount"] < min_liquidity:
                    raise ValueError("Insufficient pool liquidity")
                
                # Estimate price impact
                expected_price, price_impact = await self.estimate_price_impact(
                    amount, is_buy
                )
                
                if price_impact > max_slippage:
                    raise ValueError(
                        f"Price impact {price_impact:.2%} exceeds max slippage "
                        f"{max_slippage:.2%}"
                    )
                
                # Create transaction
                instructions = []
                
                # Add swap instruction
                # Note: This is a simplified version of Raydium's swap instruction
                # Actual implementation needs proper account setup and instruction data
                # Encode instruction data
                # Create instruction data as bytes
                instruction_data = bytearray()
                instruction_data.append(1)  # Instruction type
                instruction_data.extend(int(amount * 1e9).to_bytes(8, 'little'))
                instruction_data.extend(int(amount * 1e9 * (1 - max_slippage)).to_bytes(8, 'little'))
                
                # Get pubkeys as objects
                wallet_pubkey = wallet.pubkey()
                pool_pubkey = self.pool_address
                associated_token = get_associated_token_address(wallet_pubkey, pool_pubkey)
                
                # Create account metas for the instruction
                account_metas = [
                    AccountMeta(pubkey=wallet_pubkey, is_signer=True, is_writable=True),
                    AccountMeta(pubkey=pool_pubkey, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=associated_token, is_signer=False, is_writable=True),
                ]
                
                swap_ix = TransactionInstruction(
                    program_id=pool_pubkey,
                    accounts=account_metas,
                    data=bytes(instruction_data)
                )
                instructions.append(swap_ix)
                
                # Get recent blockhash
                blockhash = await self.client.get_latest_blockhash()
                if not blockhash or 'result' not in blockhash:
                    raise RuntimeError("Failed to get recent blockhash")

                # Get blockhash and create message
                from solders.hash import Hash

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
