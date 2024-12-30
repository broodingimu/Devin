"""Utility functions for pump.fun integration."""
import asyncio
from typing import Optional, Tuple
from solders.keypair import Keypair  # type: ignore
from solders.pubkey import Pubkey  # type: ignore
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from spl.token.instructions import get_associated_token_address
from .bonding_curve_account import get_bonding_curve_account
from .constants import SOL_DECIMAL, TOKEN_DECIMAL


async def get_token_price(client: AsyncClient, mint_str: str) -> Tuple[Optional[float], Optional[int]]:
    """Get token price from bonding curve."""
    try:
        mint = Pubkey.from_string(mint_str)
        bonding_curve_account = await get_bonding_curve_account(client, mint)
        if bonding_curve_account is None:
            print("Failed to retrieve bonding curve account...")
            return None, None
        
        virtual_sol_reserves = bonding_curve_account.virtual_sol_reserves / 10**SOL_DECIMAL
        virtual_token_reserves = bonding_curve_account.virtual_token_reserves / 10**TOKEN_DECIMAL

        token_price = virtual_sol_reserves / virtual_token_reserves
        token_decimal = TOKEN_DECIMAL
        return token_price, token_decimal

    except Exception as e:
        print(f"Error calculating token price: {e}")
        return None, None


async def get_sol_balance(client: AsyncClient, address: Pubkey) -> int:
    """Get SOL balance for an address."""
    try:
        response = await client.get_balance(address, commitment=Confirmed)
        return response.value
    except Exception as e:
        print(f"Error getting SOL balance: {e}")
        return 0


async def get_token_balance(
    client: AsyncClient, owner: Pubkey, mint: Pubkey
) -> Optional[int]:
    """Get token balance for a specific mint."""
    try:
        ata = get_associated_token_address(owner, mint)
        response = await client.get_token_account_balance(ata)
        return int(response.value.amount)
    except Exception as e:
        print(f"Error getting token balance: {e}")
        return None


async def confirm_txn(client: AsyncClient, signature: str, max_retries: int = 30) -> bool:
    """Confirm transaction with retries."""
    retries = 0
    while retries < max_retries:
        try:
            response = await client.confirm_transaction(signature)
            if response.value:
                return True
        except Exception as e:
            print(f"Error confirming transaction: {e}")
        
        await asyncio.sleep(1)
        retries += 1
    
    return False


if __name__ == "__main__":
    # Example usage
    client = AsyncClient(endpoint="https://api.mainnet-beta.solana.com")
    token_price, token_decimal = asyncio.run(get_token_price(client, "WsssSmC2mqvC9y2HW6Te67hWvjkmwF3zkNsjtpmpump"))
    print(token_price, token_decimal)
