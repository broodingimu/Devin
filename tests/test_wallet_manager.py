"""
Unit tests for wallet manager module.
"""
import pytest
import os
import logging
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from solders.keypair import Keypair

from src.wallet_manager import WalletManager

logger = logging.getLogger(__name__)

@pytest.fixture
def mock_env_vars():
    """Setup mock environment variables."""
    # Generate valid Ed25519 keypairs using 32-byte secret keys
    mock_key_1 = bytes([1] * 32).hex()  # Convert bytes to hex string
    mock_key_2 = bytes([2] * 32).hex()  # Convert bytes to hex string
    mock_key_3 = bytes([3] * 32).hex()  # Convert bytes to hex string
    mock_key_4 = bytes([4] * 32).hex()  # Convert bytes to hex string
    env_vars = {
        "RPC_ENDPOINT": "https://api.mainnet-beta.solana.com",
        "WALLET_PRIVATE_KEYS": f"{mock_key_1},{mock_key_2},{mock_key_3},{mock_key_4}"
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars

@pytest.fixture
async def wallet_manager(mock_env_vars):
    """Create wallet manager instance."""
    manager = WalletManager(min_wallet_balance=0.1)
    yield manager
    await manager.close()

@pytest.mark.asyncio
async def test_wallet_loading(wallet_manager):
    """Test wallet loading from environment variables."""
    assert len(wallet_manager.wallets) == 4
    for wallet in wallet_manager.wallets.values():
        assert isinstance(wallet, Keypair)

@pytest.mark.asyncio
async def test_get_wallet_balance(wallet_manager):
    """Test getting wallet balance."""
    mock_balance = MagicMock(value=1_000_000_000)  # 1 SOL
    with patch.object(wallet_manager.client, 'get_balance', 
                     return_value=mock_balance):
        balance = await wallet_manager.get_wallet_balance(
            str(list(wallet_manager.wallets.keys())[0])
        )
        assert balance == 1.0

@pytest.mark.asyncio
async def test_get_available_wallets(wallet_manager):
    """Test getting available wallets."""
    # Mock get_wallet_balance to return 1.0 SOL for all wallets
    async def mock_get_balance(*args, **kwargs):
        return MagicMock(value=1_000_000_000)  # 1 SOL
        
    with patch.object(wallet_manager.client, 'get_balance', 
                     side_effect=mock_get_balance):
        wallets = await wallet_manager.get_available_wallets(required_balance=0.5)
        assert len(wallets) == 4  # All wallets with sufficient balance

@pytest.mark.asyncio
async def test_wallet_cooldown(wallet_manager):
    """Test wallet cooldown period."""
    wallet_address = str(list(wallet_manager.wallets.keys())[0])
    
    # Record transactions for all wallets except the first one
    wallets = list(wallet_manager.wallets.keys())
    for wallet in wallets[1:]:  # Skip first wallet
        wallet_manager.record_transaction(wallet, "BUY", 0.1)
    
    # Mock get_wallet_balance to return 1.0 SOL
    async def mock_get_balance(*args, **kwargs):
        return MagicMock(value=1_000_000_000)  # 1 SOL
        
    with patch.object(wallet_manager.client, 'get_balance', 
                     side_effect=mock_get_balance):
        # Check wallet availability
        wallets = await wallet_manager.get_available_wallets()
    assert len(wallets) == 1  # Only one wallet available due to cooldown
    
    # Wait for cooldown - set all used wallets past cooldown
    past_time = datetime.now() - timedelta(minutes=6)
    original_wallets = list(wallet_manager.wallets.keys())
    for wallet in original_wallets[1:]:  # Reset cooldown for all wallets that had transactions
        wallet_manager.last_used[wallet] = past_time
    
    # Check wallet availability again
    with patch.object(wallet_manager.client, 'get_balance', 
                     side_effect=mock_get_balance):
        await wallet_manager.get_all_balances()  # Pre-populate balances
        wallets = await wallet_manager.get_available_wallets()
        logger.info(f"Second check - Available wallets: {len(wallets)}")
        assert len(wallets) == 4  # All wallets available

@pytest.mark.asyncio
async def test_transaction_history(wallet_manager):
    """Test transaction history recording."""
    wallet_address = str(list(wallet_manager.wallets.keys())[0])
    
    # Record transactions
    wallet_manager.record_transaction(wallet_address, "BUY", 0.1)
    wallet_manager.record_transaction(wallet_address, "SELL", 0.2)
    
    history = wallet_manager.get_wallet_history(wallet_address)
    assert len(history) == 2
    assert history[0]["type"] == "BUY"
    assert history[0]["amount"] == 0.1
    assert history[1]["type"] == "SELL"
    assert history[1]["amount"] == 0.2
