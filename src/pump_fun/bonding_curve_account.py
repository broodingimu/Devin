from dataclasses import dataclass
from construct import Struct, Int64ul, Flag, Padding
from typing import Optional, Dict, Any
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from spl.token.instructions import get_associated_token_address
from .constants import PUMP_FUN_PROGRAM, SOL_DECIMAL, TOKEN_DECIMAL

@dataclass
class BondingCurveAccount:
    mint: Pubkey
    bonding_curve: Pubkey
    associated_bonding_curve: Pubkey
    discriminator: int
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool

    def __init__(
        self,
        mint: Pubkey,
        bonding_curve: Pubkey,
        associated_bonding_curve: Pubkey,
        discriminator: int,
        virtual_token_reserves: int,
        virtual_sol_reserves: int,
        real_token_reserves: int,
        real_sol_reserves: int,
        token_total_supply: int,
        complete: bool
    ):
        self.mint = mint
        self.bonding_curve = bonding_curve
        self.associated_bonding_curve = associated_bonding_curve
        self.discriminator = discriminator
        self.virtual_token_reserves = virtual_token_reserves
        self.virtual_sol_reserves = virtual_sol_reserves
        self.real_token_reserves = real_token_reserves
        self.real_sol_reserves = real_sol_reserves
        self.token_total_supply = token_total_supply
        self.complete = complete

    def get_token_price(self) -> float:
        if self.complete:
            raise ValueError("Curve is complete")
        return (self.virtual_sol_reserves / 10**SOL_DECIMAL) / (self.virtual_token_reserves / 10**TOKEN_DECIMAL)
    
    def get_buy_amount_out(self, amount: int, fee_basis_points: int = 100) -> int:
        if self.complete:
            raise ValueError("Curve is complete")
        if amount <= 0:
            return 0

        # Adjust input amount for fees if any
        amount_after_fee = amount
        if fee_basis_points > 0:
            fee = (amount * fee_basis_points) // 10000
            amount_after_fee = amount - fee

        # Calculate the product of virtual reserves
        n = self.virtual_sol_reserves * self.virtual_token_reserves
        # Calculate the new virtual sol reserves after the purchase
        i = self.virtual_sol_reserves + amount_after_fee
        # Calculate the new virtual token reserves after the purchase
        r = n // i + 1
        # Calculate the amount of tokens to be purchased
        s = self.virtual_token_reserves - r
        # Return the minimum of the calculated tokens and real token reserves
        return min(s, self.real_token_reserves)

    def get_sell_amount_out(self, amount: int, fee_basis_points: int = 100) -> int:
        if self.complete:
            raise ValueError("Curve is complete")
        if amount <= 0:
            return 0

        # Calculate the proportional amount of virtual sol reserves to be received
        n = (amount * self.virtual_sol_reserves) // (self.virtual_token_reserves + amount)
        # Calculate the fee amount in the same units
        a = (n * fee_basis_points) // 10000
        # Return the net amount after deducting the fee
        return n - a

    def get_market_cap_sol(self) -> int:
        if self.virtual_token_reserves == 0:
            return 0
        return (self.token_total_supply * self.virtual_sol_reserves) // self.virtual_token_reserves

    def get_final_market_cap_sol(self, fee_basis_points: int = 100) -> int:
        total_sell_value = self.get_buy_out_amount_out(self.real_token_reserves, fee_basis_points)
        total_virtual_value = self.virtual_sol_reserves + total_sell_value
        total_virtual_tokens = self.virtual_token_reserves - self.real_token_reserves
        
        if total_virtual_tokens == 0:
            return 0
        return (self.token_total_supply * total_virtual_value) // total_virtual_tokens

    def get_buy_out_amount_out(self, amount: int, fee_basis_points: int = 100) -> int:
        sol_tokens = self.real_sol_reserves if amount < self.real_sol_reserves else amount
        total_sell_value = (
            (sol_tokens * self.virtual_sol_reserves) //
            (self.virtual_token_reserves - sol_tokens) + 1
        )
        fee = (total_sell_value * fee_basis_points) // 10000
        return total_sell_value + fee

    @staticmethod
    def from_buffer(buffer: bytes, mint: Pubkey, bonding_curve: Pubkey, associated_bonding_curve: Pubkey) -> 'BondingCurveAccount':
        bonding_curve_struct = Struct(
            Padding(8),
            "virtualTokenReserves" / Int64ul,
            "virtualSolReserves" / Int64ul,
            "realTokenReserves" / Int64ul,
            "realSolReserves" / Int64ul,
            "tokenTotalSupply" / Int64ul,
            "complete" / Flag
        )
        
        parsed_data = bonding_curve_struct.parse(buffer)
        return BondingCurveAccount(
            discriminator=int.from_bytes(buffer[:8], byteorder='little'),
            virtual_token_reserves=parsed_data.virtualTokenReserves,
            virtual_sol_reserves=parsed_data.virtualSolReserves,
            real_token_reserves=parsed_data.realTokenReserves,
            real_sol_reserves=parsed_data.realSolReserves,
            token_total_supply=parsed_data.tokenTotalSupply,
            complete=parsed_data.complete,
            mint=mint,
            bonding_curve=bonding_curve,
            associated_bonding_curve=associated_bonding_curve
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert the account data to a dictionary format"""
        return {
            "mint": str(self.mint),
            "bonding_curve": str(self.bonding_curve),
            "associated_bonding_curve": str(self.associated_bonding_curve),
            "real_token_reserves": self.real_token_reserves,
            "real_sol_reserves": self.real_sol_reserves,
            "virtual_token_reserves": self.virtual_token_reserves,
            "virtual_sol_reserves": self.virtual_sol_reserves,
            "token_total_supply": self.token_total_supply,
            "complete": self.complete
        }

def derive_bonding_curve_accounts(mint: Pubkey, program_id: Pubkey) -> tuple[Pubkey, Pubkey]:
    """Derive bonding curve related accounts from mint"""
    try:
        bonding_curve, _ = Pubkey.find_program_address(
            ["bonding-curve".encode(), bytes(mint)],
            program_id
        )
        associated_bonding_curve = get_associated_token_address(bonding_curve, mint)
        return bonding_curve, associated_bonding_curve
    except Exception as e:
        raise ValueError(f"Failed to derive bonding curve accounts: {str(e)}")

async def get_bonding_curve_account(
    client: AsyncClient, 
    mint: Pubkey
) -> Optional[BondingCurveAccount]:
    """Fetch and parse bonding curve account data"""
    try:
        bonding_curve, associated_bonding_curve = derive_bonding_curve_accounts(mint, PUMP_FUN_PROGRAM)
        if bonding_curve is None or associated_bonding_curve is None:
            return None
        
        account_info = await client.get_account_info(bonding_curve)
        if account_info.value is None:
            return None
        
        return BondingCurveAccount.from_buffer(
            account_info.value.data,
            mint=mint,
            bonding_curve=bonding_curve,
            associated_bonding_curve=associated_bonding_curve
        )
    except Exception as e:
        print(f"Error fetching bonding curve account: {str(e)}")
        return None

if __name__ == "__main__":
    from sol_trading_bot.config import SOLANA_TRADING_ENGINE_CONFIG
    import asyncio
    # client = AsyncClient(endpoint=SOLANA_TRADING_ENGINE_CONFIG["rpc_url"])
    # bonding_curve_account = asyncio.run(get_bonding_curve_account(client, Pubkey.from_string("APoiadVjGJ2uzcZwGLmGQszZ6GjTVbWfVFuPDe3Spump")))
    # print(bonding_curve_account.get_buy_price(100000 * 10**6))
    # print(bonding_curve_account.get_sell_price(100000 * 10**6))
    # print(bonding_curve_account.get_token_price())
    # print(bonding_curve_account.get_market_cap_sol())
    # print(bonding_curve_account.get_final_market_cap_sol())
    bonding_curve, associated_bonding_curve = derive_bonding_curve_accounts(Pubkey.from_string("B1xGq2VDKXx3RyFurJYbzgBsWM7fLtf6L9TmzEGas6sU"), PUMP_FUN_PROGRAM)
    print(bonding_curve)
    print(associated_bonding_curve)
