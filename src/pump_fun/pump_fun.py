import struct
import requests
from dataclasses import dataclass
from typing import Tuple, List, Optional
from solana.rpc.types import TokenAccountOpts, TxOpts
from spl.token.instructions import (
    create_associated_token_account, 
    get_associated_token_address, 
    close_account, 
    CloseAccountParams
)
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.instruction import Instruction # type: ignore
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price # type: ignore
from solders.transaction import VersionedTransaction # type: ignore
from solders.message import MessageV0 # type: ignore
from solana.transaction import AccountMeta
from solana.rpc.async_api import AsyncClient

from anchorpy import Program, Context

from .constants import (
    SOL_DECIMAL, TOKEN_DECIMAL, SYSTEM_PROGRAM, TOKEN_PROGRAM,
    PUMP_FUN_PROGRAM
)
from .bonding_curve_account import get_bonding_curve_account
from .utils import get_sol_balance, get_token_balance, confirm_txn

# Constants
GLOBAL = Pubkey.from_string("GLBLafk39H4dxSfYfJ6KtfY4Jr3xYgHDfZxjsBxKvN2K")
FEE_RECIPIENT = Pubkey.from_string("FeeR23JxhVDX2rEPXg6pVnYFGqEpV6tmVvh2zXbzWYE")
ASSOC_TOKEN_ACC_PROG = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
EVENT_AUTHORITY = Pubkey.from_string("EvntAuThUZDr1pWyDh6wp3H3ZXLGn2wFWGbenF9YPvU")
MPL_TOKEN_METADATA_PROGRAM = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

@dataclass
class CreateTokenMetadata:
    name: str
    symbol: str
    description: str
    twitter: Optional[str] = None
    telegram: Optional[str] = None
    website: Optional[str] = None
    

async def get_create_token_instruction_with_IDL(
    program: Program,
    mint: Pubkey,
    user: Pubkey,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    token_metadata: CreateTokenMetadata,
    image_path: str
) -> Instruction:
    """
    Create instruction for creating a new token with metadata.
    Args:
        program: Anchor program instance
        mint: Mint account pubkey (must be signer)
        user: User's pubkey (creator/payer)
        token_metadata: Token metadata object
        image_path: Path to token image
    """
    # Upload image and metadata
    with open(image_path, "rb") as f:
        img_data = f.read()
        url = "https://pump.fun/api/ipfs"
        data = {
            "name": token_metadata.name,
            "symbol": token_metadata.symbol,
            "description": token_metadata.description,
            "twitter": token_metadata.twitter,
            "telegram": token_metadata.telegram,
            "website": token_metadata.website,
            "showName": "true"
        }
        files = {
            "file": (f"{token_metadata.name}.png", img_data, "image/png")
        }

        resp = requests.post(url, files=files, data=data)
        resp_data = resp.json()
        metadata_uri = resp_data["metadataUri"]
        print("Metadata URI:", metadata_uri)

    # Get mint authority PDA
    (mint_authority, _) = Pubkey.find_program_address(
        [b"mint-authority"],
        program.program_id
    )

    # Get metadata PDA
    (metadata, _) = Pubkey.find_program_address(
        [b"metadata", bytes(MPL_TOKEN_METADATA_PROGRAM), bytes(mint)],
        MPL_TOKEN_METADATA_PROGRAM
    )

    # Create instruction

    accounts = {
        "mint": mint,
        "mint_authority": mint_authority,
        "bonding_curve": bonding_curve,
        "associated_bonding_curve": associated_bonding_curve,
        "global": GLOBAL,
        "mpl_token_metadata": MPL_TOKEN_METADATA_PROGRAM,
        "metadata": metadata,
        "user": user,
        "system_program": SYSTEM_PROGRAM,
        "token_program": TOKEN_PROGRAM,
        "associated_token_program": ASSOC_TOKEN_ACC_PROG,
        "rent": RENT,
        "event_authority": EVENT_AUTHORITY,
        "program": PUMP_FUN_PROGRAM
    }

    create_ix = program.instruction["create"](
        token_metadata.name,
        token_metadata.symbol,
        metadata_uri,
        ctx=Context(accounts=accounts)
    )

    return create_ix


async def get_buy_instructions_with_IDL(
    program: Program,
    mint: Pubkey,
    payer: Pubkey,
    user: Pubkey,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    amount_out_lamports: int,
    max_sol_cost_lamports: int,
) -> List[Instruction]:
    """
    Create all instructions needed for a buy transaction, including token account creation if needed.
    """
    instructions: List[Instruction] = []

    # Check if token account exists and create if needed
    ata = get_associated_token_address(user, mint)
    try:
        await program.provider.get_token_accounts_by_owner(user, TokenAccountOpts(mint))
    except:
        # Token account doesn't exist, create it
        create_ata_ix = create_associated_token_account(
            payer, user, mint
        )
        instructions.append(create_ata_ix)

    accounts = {
        "global": GLOBAL,
        "fee_recipient": FEE_RECIPIENT,
        "mint": mint,
        "bonding_curve": bonding_curve,
        "associated_bonding_curve": associated_bonding_curve,
        "associated_user": ata,
        "user": payer,
        "system_program": SYSTEM_PROGRAM,
        "token_program": TOKEN_PROGRAM,
        "rent": RENT,
        "event_authority": EVENT_AUTHORITY,
        "program": PUMP_FUN_PROGRAM
    }

    buy_ix = program.instruction["buy"](
        amount_out_lamports,
        max_sol_cost_lamports,
        ctx=Context(accounts=accounts)
    )
    instructions.append(buy_ix)
    return instructions


async def get_sell_instructions_with_IDL(
    program: Program,
    mint: Pubkey,
    payer: Pubkey,
    user: Pubkey,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    amount_in_lamports: int,
    min_sol_output_lamports: int,
    selling_all: bool = False
) -> List[Instruction]:
    """
    Create all instructions needed for a sell transaction, including close account if selling all.
    """
    instructions: List[Instruction] = []

    # Get token account
    ata = get_associated_token_address(user, mint)

    # Create sell instruction
    sell_ix = await program.instruction.sell(
        amount_in_lamports,
        min_sol_output_lamports,
        accounts={
            "global": GLOBAL,
            "feeRecipient": FEE_RECIPIENT,
            "mint": mint,
            "bondingCurve": bonding_curve,
            "associatedBondingCurve": associated_bonding_curve,
            "associatedUser": ata,
            "user": payer,
        }
    )
    instructions.append(sell_ix)

    # Add close account instruction if selling all tokens
    if selling_all:
        close_account_ix = close_account(
            CloseAccountParams(TOKEN_PROGRAM, ata, user, user)
        )
        instructions.append(close_account_ix)

    return instructions


async def get_buy_instructions(
    client: AsyncClient,
    mint: Pubkey,
    user: Pubkey,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    amount_in_lamports: int,
    max_sol_cost_lamports: int,
    unit_budget: int,
    unit_price: int,
) -> List[Instruction]:
    """
    Create all instructions needed for a buy transaction, including token account creation if needed.
    """
    instructions: List[Instruction] = []
    
    # Add compute budget instructions
    # instructions.append(set_compute_unit_limit(unit_budget))
    # instructions.append(set_compute_unit_price(unit_price))
    
    # Check if token account exists and create if needed
    token_account = get_associated_token_address(user, mint)
    try:
        await client.get_token_accounts_by_owner(user, TokenAccountOpts(mint))
    except:
        # Token account doesn't exist, create it
        instructions.append(
            create_associated_token_account(user, user, mint)
        )

    # Create main buy instruction
    keys = [
        AccountMeta(pubkey=GLOBAL, is_signer=False, is_writable=False),
        AccountMeta(pubkey=FEE_RECIPIENT, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(pubkey=associated_bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(pubkey=token_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=RENT, is_signer=False, is_writable=False),
        AccountMeta(pubkey=EVENT_AUTHORITY, is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_FUN_PROGRAM, is_signer=False, is_writable=False)
    ]

    data = bytearray()
    data.extend(bytes.fromhex("66063d1201daebea"))  # Buy instruction discriminator
    data.extend(struct.pack('<Q', amount_in_lamports))
    data.extend(struct.pack('<Q', max_sol_cost_lamports))
    
    instructions.append(Instruction(PUMP_FUN_PROGRAM, bytes(data), keys))
    
    return instructions

async def get_sell_instructions(
    client: AsyncClient,
    mint: Pubkey,
    user: Pubkey,
    bonding_curve: Pubkey,
    associated_bonding_curve: Pubkey,
    amount_in_lamports: int,
    min_sol_output_lamports: int,
    selling_all: bool,
    unit_budget: int,
    unit_price: int,
) -> List[Instruction]:
    """
    Create all instructions needed for a sell transaction.
    Automatically determines if close account instruction is needed based on sell amount.
    """
    instructions: List[Instruction] = []
    
    # Add compute budget instructions
    instructions.append(set_compute_unit_limit(unit_budget))
    instructions.append(set_compute_unit_price(unit_price))

    # Get token account
    token_account = get_associated_token_address(user, mint)

    # Create main sell instruction
    keys = [
        AccountMeta(pubkey=GLOBAL, is_signer=False, is_writable=False),
        AccountMeta(pubkey=FEE_RECIPIENT, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(pubkey=associated_bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(pubkey=token_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=ASSOC_TOKEN_ACC_PROG, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=EVENT_AUTHORITY, is_signer=False, is_writable=False),
        AccountMeta(pubkey=PUMP_FUN_PROGRAM, is_signer=False, is_writable=False)
    ]

    data = bytearray()
    data.extend(bytes.fromhex("33e685a4017f83ad"))  # Sell instruction discriminator
    data.extend(struct.pack('<Q', amount_in_lamports))
    data.extend(struct.pack('<Q', min_sol_output_lamports))
    
    instructions.append(Instruction(PUMP_FUN_PROGRAM, bytes(data), keys))

    # Add close account instruction if selling all tokens
    if selling_all:
        close_account_instructions = close_account(
            CloseAccountParams(TOKEN_PROGRAM, token_account, user, user)
        )
        instructions.append(close_account_instructions)

    return instructions


async def buy(
    client: AsyncClient,
    payer_keypair: Keypair,
    mint_str: str,
    sol_in: float = 0.01,
    slippage_basis_points: int = 250,
    unit_budget: int = 200_000,
    unit_price: int = 1_000
) -> Tuple[bool, Optional[str]]:
    """
    Buy tokens using the pump fun protocol
    
    Args:
        client: Solana client
        payer_keypair: Keypair of the buyer
        mint_str: Mint address as string
        sol_in: Amount of SOL to spend
        slippage_basis_points: Slippage tolerance in basis points (1 bp = 0.01%)
        unit_budget: Compute unit budget
        unit_price: Compute unit price
    
    Returns:
        (success: bool, signature: Optional[str])
    """
    try:
        if not (0 <= slippage_basis_points <= 10000):
            raise ValueError("Slippage must be between 0 and 10000")

        # Get owner and mint
        owner = payer_keypair.pubkey()
        mint = Pubkey.from_string(mint_str)
        
        # Get bonding curve account
        bonding_curve_account = await get_bonding_curve_account(client, mint)
        if not bonding_curve_account:
            print("Failed to retrieve bonding curve account")
            return False, None
        if bonding_curve_account.complete:
            print("Bonding curve is complete, cannot buy")
            return False, None

        # Calculate amounts
        amount_in_lamports = int(sol_in * 10**SOL_DECIMAL)
        amount_out_lamports = bonding_curve_account.get_buy_amount_out(amount_in_lamports)
        slippage_adjustment = 1 + (slippage_basis_points / 10000)
        max_sol_cost_lamports = int(amount_in_lamports * slippage_adjustment)
        
        # Check balance
        balance = await get_sol_balance(client, owner)
        if max_sol_cost_lamports > balance:
            print(f"Insufficient balance: required {max_sol_cost_lamports}, have {balance}")
            return False, None
        print(f"Sol In: {sol_in} | Amount Out: {amount_out_lamports / 10**TOKEN_DECIMAL} | Max Sol Cost: {max_sol_cost_lamports / 10**SOL_DECIMAL}")

        # Create instructions
        """
        instructions = await get_buy_instructions(
            client=client,
            mint=mint,
            user=owner,
            bonding_curve=bonding_curve_account.bonding_curve,
            associated_bonding_curve=bonding_curve_account.associated_bonding_curve,
            amount_in_lamports=amount_in_lamports,
            max_sol_cost_lamports=max_sol_cost_lamports,
            unit_budget=unit_budget,
            unit_price=unit_price
        )
        """
        from sol_trading_bot.config import SOLANA_TRADING_ENGINE_CONFIG
        from anchorpy.provider import Provider, Confirmed
        from anchorpy import Idl, Program, Context, Wallet
        from pathlib import Path
        import json
        payer_kp = Keypair.from_base58_string(SOLANA_TRADING_ENGINE_CONFIG["private_key"])
        wallet = Wallet(payer_kp)
        client = AsyncClient(endpoint=SOLANA_TRADING_ENGINE_CONFIG["rpc_url"])
        provider = Provider(client, wallet, Confirmed)
        IDL_PATH = Path(__file__).parent / "IDL" / "pump_fun.json"
        with open(IDL_PATH, "r") as f:
            idl_data = json.load(f)
        idl_json_str = json.dumps(idl_data)
        idl = Idl.from_json(idl_json_str)
        program = Program(idl, PUMP_FUN_PROGRAM, provider)

        instructions = await get_buy_instructions_with_IDL(
            program=program,
            mint=mint,
            payer=owner,
            user=owner,
            bonding_curve=bonding_curve_account.bonding_curve,
            associated_bonding_curve=bonding_curve_account.associated_bonding_curve,
            amount_out_lamports=amount_out_lamports,
            max_sol_cost_lamports=max_sol_cost_lamports,
        )
        # Build and send transaction
        latest_blockhash = (await client.get_latest_blockhash()).value.blockhash
        message = MessageV0.try_compile(
            payer=owner,
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=latest_blockhash
        )
        transaction = VersionedTransaction(message, [payer_keypair])

        # Send transaction
        print("Sending transaction...")
        txn_sig = (await client.send_transaction(
            txn=transaction,
            opts=TxOpts(skip_preflight=True)
        )).value
        print("Transaction Signature:", txn_sig)

        # Confirm transaction
        print("Confirming transaction...")
        confirmed = await confirm_txn(client, txn_sig)
        if not confirmed:
            print("Transaction failed to confirm")
            return False, None
        print("Transaction confirmed:", confirmed)
        return True, txn_sig

    except Exception as e:
        print(f"Buy error: {e}")
        return False, None

async def sell(
    client: AsyncClient,
    payer_keypair: Keypair,
    mint_str: str,
    percentage: int = 100,
    slippage_basis_points: int = 250,
    unit_budget: int = 200_000,
    unit_price: int = 1_000
) -> Tuple[bool, Optional[str]]:
    """
    Sell tokens using the pump fun protocol
    
    Args:
        client: Solana client
        payer_keypair: Keypair of the seller
        mint_str: Mint address as string
        percentage: Percentage of tokens to sell (1-100)
        slippage_basis_points: Slippage tolerance in basis points (1 bp = 0.01%)
        unit_budget: Compute unit budget
        unit_price: Compute unit price
    
    Returns:
        (success: bool, signature: Optional[str])
    """
    try:
        if not (1 <= percentage <= 100):
            raise ValueError("Percentage must be between 1 and 100")
        if not (0 <= slippage_basis_points <= 10000):
            raise ValueError("Slippage must be between 0 and 10000")

        # Get owner and mint
        owner = payer_keypair.pubkey()
        mint = Pubkey.from_string(mint_str)

        # Get bonding curve account
        bonding_curve_account = await get_bonding_curve_account(client, mint)
        if not bonding_curve_account:
            print("Failed to retrieve bonding curve account")
            return False, None
        if bonding_curve_account.complete:
            print("Bonding curve is complete, cannot sell")
            return False, None

        # Get token balance
        token_balance = await get_token_balance(client, owner, mint)
        if token_balance == 0 or token_balance is None:
            print("Token balance is zero")
            return False, None

        if percentage == 100:
            selling_all = True
        else:
            selling_all = False

        # Calculate amounts
        amount_in_lamports = int(token_balance * (percentage / 100))
        amount_out_lamports = bonding_curve_account.get_sell_amount_out(amount_in_lamports)
        slippage_adjustment = 1 - (slippage_basis_points / 10000)
        min_sol_output_lamports = int(amount_out_lamports * slippage_adjustment)
        print(f"Amount: {amount_in_lamports / 10**TOKEN_DECIMAL} | Minimum Sol Out: {min_sol_output_lamports / 10**SOL_DECIMAL}")
        # Create instructions
        instructions = await get_sell_instructions(
            client=client,
            mint=mint,
            user=owner,
            bonding_curve=bonding_curve_account.bonding_curve,
            associated_bonding_curve=bonding_curve_account.associated_bonding_curve,
            amount_in_lamports=amount_in_lamports,
            min_sol_output_lamports=min_sol_output_lamports,
            selling_all=selling_all,
            unit_budget=unit_budget,
            unit_price=unit_price
        )

        # Build and send transaction
        latest_blockhash = (await client.get_latest_blockhash()).value.blockhash
        message = MessageV0.try_compile(
            payer=owner,
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=latest_blockhash
        )
        transaction = VersionedTransaction(message, [payer_keypair])

        # Send transaction
        print("Sending transaction...")
        txn_sig = (await client.send_transaction(
            txn=transaction,
            opts=TxOpts(skip_preflight=True)
        )).value
        print("Transaction Signature:", txn_sig)

        # Confirm transaction
        print("Confirming transaction...")
        confirmed = await confirm_txn(client, txn_sig)
        if not confirmed:
            print("Transaction failed to confirm")
            return False, None
        print("Transaction confirmed:", confirmed)
        return True, txn_sig

    except Exception as e:
        print(f"Sell error: {e}")
        return False, None


if __name__ == "__main__":
    import asyncio
    from sol_trading_bot.config import SOLANA_TRADING_ENGINE_CONFIG
    client = AsyncClient(SOLANA_TRADING_ENGINE_CONFIG['rpc_url'])
    payer_keypair = Keypair.from_base58_string(SOLANA_TRADING_ENGINE_CONFIG['private_key'])
    UNIT_BUDGET = SOLANA_TRADING_ENGINE_CONFIG['unit_budget']
    UNIT_PRICE = SOLANA_TRADING_ENGINE_CONFIG['unit_price']
    # print(asyncio.run(pump_sell(client, payer_keypair, "HYuxVqwGcKtDM8potkPGqQPrbzGa4EYsZrSCUPrQpump", 100, 5)))
    # print(asyncio.run(buy(client, payer_keypair, "BoeMPzgSNNpMAJXBqwGhhkjxNSUYeHniwGWsUozupump", 0.001, 3000, UNIT_BUDGET, UNIT_PRICE)))
    print(asyncio.run(sell(client, payer_keypair, "BoeMPzgSNNpMAJXBqwGhhkjxNSUYeHniwGWsUozupump", 100, 300, UNIT_BUDGET, UNIT_PRICE)))
