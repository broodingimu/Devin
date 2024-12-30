import json
import base58
import requests
import time
import random
import asyncio
from pathlib import Path
from typing import List, Any
from spl.token.instructions import create_associated_token_account, get_associated_token_address
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.instruction import Instruction # type: ignore
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price # type: ignore
from solders.transaction import VersionedTransaction # type: ignore
from solders.message import MessageV0 # type: ignore
from solders.system_program import transfer, TransferParams # type: ignore
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from anchorpy import Program, Provider, Wallet, Idl

from jito_searcher_client import get_async_searcher_client
from jito_searcher_client.convert import tx_to_protobuf_packet, versioned_tx_to_protobuf_packet
from jito_searcher_client.generated.bundle_pb2 import Bundle
from jito_searcher_client.generated.searcher_pb2_grpc import SearcherServiceStub
from jito_searcher_client.generated.searcher_pb2 import (
    SendBundleRequest,
    SendBundleResponse,
    NextScheduledLeaderRequest,
    NextScheduledLeaderResponse
)

from sol_trading_bot.common.jito_service import JitoJsonRpcSDK

from sol_trading_bot.common.constants import (
    SOL_DECIMAL, TOKEN_DECIMAL, GLOBAL, FEE_RECIPIENT, 
    SYSTEM_PROGRAM, TOKEN_PROGRAM, ASSOC_TOKEN_ACC_PROG, 
    RENT, EVENT_AUTHORITY, PUMP_FUN_PROGRAM, MPL_TOKEN_METADATA_PROGRAM
)

from sol_trading_bot.pump_fun.pump_fun import get_create_token_instruction_with_IDL, get_buy_instructions_with_IDL, get_sell_instructions_with_IDL, CreateTokenMetadata
from sol_trading_bot.pump_fun.bonding_curve_account import get_bonding_curve_account, derive_bonding_curve_accounts
from sol_trading_bot.config import SOLANA_TRADING_ENGINE_CONFIG, JITO_CONFIG



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

def load_keypairs() -> List[Keypair]:
    # Implement your logic to load multiple Keypairs from disk
    return []

def chunk_array(lst: List[Any], size: int) -> List[List[Any]]:
    return [lst[i:i+size] for i in range(0, len(lst), size)]


def get_random_tip_account() -> Pubkey:
    JITO_RPC_URL = JITO_CONFIG["rpc_url"]
    jito_rpc_client = JitoJsonRpcSDK(JITO_RPC_URL)
    response = jito_rpc_client.get_tip_accounts()
    tip_accounts = response['data']['result']
    return Pubkey.from_string(random.choice(tip_accounts))


async def send_bundle(bundled_txns: List[VersionedTransaction]):

    BLOCK_ENGINE_URL = JITO_CONFIG["block_engine_url"]
    jito_block_engine_client = await get_async_searcher_client(BLOCK_ENGINE_URL)

    is_leader_slot = False
    print("waiting for jito leader...")
    while not is_leader_slot:
        await asyncio.sleep(0.5)
        next_leader: NextScheduledLeaderResponse = await jito_block_engine_client.GetNextScheduledLeader(
            NextScheduledLeaderRequest())
        num_slots_to_leader = next_leader.next_leader_slot - next_leader.current_slot
        print(f"waiting {num_slots_to_leader} slots to jito leader")
        is_leader_slot = num_slots_to_leader <= 5

    packets = [versioned_tx_to_protobuf_packet(tx) for tx in bundled_txns]
    uuid_response = await jito_block_engine_client.SendBundle(SendBundleRequest(bundle=Bundle(header=None, packets=packets)))
    print(f"bundle uuid: {uuid_response.uuid}")
    return uuid_response.uuid


async def poll_bundle_status(bundle_id: str, timeout: int = 60, poll_interval: int = 3):
    JITO_RPC_URL = JITO_CONFIG["rpc_url"]
    jito_rpc_client = JitoJsonRpcSDK(JITO_RPC_URL)
    start_time = time.time()
    last_status = ''

    while (time.time() - start_time) < timeout:
        try:
            response = jito_rpc_client.get_inflight_bundle_statuses([bundle_id])
            bundle_status_data = response['data']['result']
            status = bundle_status_data['value'][0].get('status', 'Unknown') if bundle_status_data else 'Unknown'

            if status != last_status:
                last_status = status

            if status == 'Invalid':
                print(f"Bundle {status.lower()}. Waiting...")
                raise Exception(f"Bundle failed with status: {status}")

            if status == 'Pending':
                print(f"Bundle {status.lower()}. Pending...")
            
            if status == 'Landed':
                print(f"✅ Bundle {status.lower()}. Landed...")
                return True

            if status == 'Failed':
                print(f"Bundle {status.lower()}. Exiting...")
                raise Exception(f"Bundle failed with status: {status}")
            
            
            await asyncio.sleep(poll_interval)
        except Exception as e:
            print('\u274c - Error polling bundle status:', e)

    raise Exception("Polling timeout reached without confirmation")


async def create_and_buy(
        program: Program,
        payer_kp: Keypair,
        mint_kp: Keypair,
        metadata: CreateTokenMetadata,
        image_path: str
) -> VersionedTransaction:
    """
    Create a new token and buy it
    """
    sol_in = 0.01
    slippage_basis_points = 200
    tip_amt = 0.005
    
    payer = payer_kp.pubkey()
    mint = mint_kp.pubkey()
    bonding_curve, associated_bonding_curve = derive_bonding_curve_accounts(mint, PUMP_FUN_PROGRAM)

    
    amount_in_lamports = int(sol_in * 10**SOL_DECIMAL)
    amount_out_lamports = 354000 * 10**TOKEN_DECIMAL
    # amount_out_lamports = bonding_curve_account.get_buy_amount_out(amount_in_lamports)
    max_sol_cost_lamports = int(amount_in_lamports * (1 + slippage_basis_points / 10000))

    create_ix = await get_create_token_instruction_with_IDL(program,
                                                            mint,
                                                            payer,
                                                            bonding_curve,
                                                            associated_bonding_curve,
                                                            metadata,
                                                            image_path)
    buy_ixs = await get_buy_instructions_with_IDL(program,
                                                 mint,
                                                 payer,
                                                 payer,
                                                 bonding_curve,
                                                 associated_bonding_curve,
                                                 amount_out_lamports,
                                                 max_sol_cost_lamports)

    tip_ix = transfer(
        TransferParams(
            from_pubkey=payer, to_pubkey=get_random_tip_account(),
            lamports=int(tip_amt * 10**SOL_DECIMAL)  #TIP AMOUNT
        )
    )
    
    final_ixs = [create_ix, *buy_ixs, tip_ix]
    latest_blockhash = (await program.provider.connection.get_latest_blockhash()).value.blockhash
    message = MessageV0.try_compile(
        payer=payer,
        instructions=final_ixs,
        address_lookup_table_accounts=[],
        recent_blockhash=latest_blockhash
    )
    transaction = VersionedTransaction(message, [payer_kp, mint_kp])

    return transaction

async def create_multiple_wallet_swaps(
        program: Program,
        payer_kp: Keypair,
        keypairs: List[Keypair],
        mint: Pubkey
) -> List[VersionedTransaction]:

    payer = payer_kp.pubkey()
    txs_signed = []
    sol_in = 0.001
    slippage_basis_points = 500
    """
    key_info_path = Path(__file__).parent / "keyInfo.json"
    if key_info_path.exists():
        with open(key_info_path, "r") as f:
            key_info = json.load(f)
    else:
        key_info = {}
    """

    # Chunk the keypairs into manageable sizes
    keypair_chunks = chunk_array(keypairs, 5)

    for chunk in keypair_chunks:
        instructions_for_chunk = []
        signers = [payer]
        for keypair in chunk:
            user = keypair.pubkey()
            bonding_curve_account = await get_bonding_curve_account(program.provider.connection, mint)
            # Calculate amounts
            amount_in_lamports = int(sol_in * 10**SOL_DECIMAL)
            amount_out_lamports = bonding_curve_account.get_buy_amount_out(amount_in_lamports)
            slippage_adjustment = 1 + (slippage_basis_points / 10000)
            max_sol_cost_lamports = int(amount_in_lamports * slippage_adjustment)
            buy_ixs = get_buy_instructions_with_IDL(program=program,
                                                    mint=mint,
                                                    payer=payer,
                                                    user=user,
                                                    bonding_curve=bonding_curve_account.bonding_curve,
                                                    associated_bonding_curve=bonding_curve_account.associated_bonding_curve,
                                                    amount_in_lamports=amount_in_lamports,
                                                    max_sol_cost_lamports=max_sol_cost_lamports)
            instructions_for_chunk.extend(buy_ixs)
            signers.append(keypair)

        latest_blockhash = (await program.provider.connection.get_latest_blockhash()).value.blockhash
        message = MessageV0.try_compile(
            payer=payer,
            instructions=instructions_for_chunk,
            address_lookup_table_accounts=[],
            recent_blockhash=latest_blockhash
        )
        transaction = VersionedTransaction(message, signers)
        txs_signed.append(transaction)

    return txs_signed


async def main():
    """
    keypairs = load_keypairs()

    key_info_path = Path(__file__).parent / "keyInfo.json"
    if key_info_path.exists():
        with open(key_info_path, "r") as f:
            key_info = json.load(f)
    else:
        key_info = {}

    mint_pk = base58.b58decode(key_info["mintPk"])
    mint_kp = Keypair.from_secret_key(mint_pk)
    print(f"Mint: {mint_kp.pubkey()}")
    """
    mint_kp = Keypair()
    mint = mint_kp.pubkey()
    print(f"Mint: {mint}")
    """
    name = input("Name of your token: ")
    symbol = input("Symbol of your token: ")
    description = input("Description of your token: ")
    twitter = input("Twitter of your token: ")
    telegram = input("Telegram of your token: ")
    website = input("Website of your token: ")
    tip_amt = float(input("Jito tip in SOL: "))
    image_path = input("Path to your image file path: ")
    """
    name = "ant"
    symbol = "ant"
    description = "ant"
    twitter = "ant"
    telegram = "ant"
    website = "ant"
    tip_amt = 0.001
    image_path = Path(__file__).parent / "images" / "ant.png"
    
    metadata = CreateTokenMetadata(name, symbol, description, twitter, telegram, website)

    init_txn = await create_and_buy(program, payer_kp, mint_kp, metadata, image_path)

    # multi_wallet_swap_txns = await create_multiple_wallet_swaps(program, payer_kp, keypairs, mint)

    bundled_txns = [init_txn]
    # bundled_txns.extend(multi_wallet_swap_txns)

    bundle_id = await send_bundle(bundled_txns)
    await poll_bundle_status(bundle_id)

if __name__ == "__main__":

    asyncio.run(main())