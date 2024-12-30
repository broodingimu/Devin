"""
Unit tests for Raydium interface module.
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from decimal import Decimal
from solders.keypair import Keypair

from src.raydium_interface import RaydiumInterface

@pytest.fixture
def mock_pool_data():
    """Mock pool data for testing."""
    return {
        "token_a_amount": 100000000000000,  # 100B tokens
        "token_b_amount": 200000000000000,  # 200B tokens
        "fee_rate": 0.003,  # 0.3% fee
    }

@pytest.fixture
async def raydium_interface():
    """Create Raydium interface instance."""
    interface = RaydiumInterface("11111111111111111111111111111111")
    yield interface
    await interface.close()

@pytest.mark.asyncio
async def test_get_pool_price(raydium_interface, mock_pool_data):
    """Test getting pool price."""
    with patch.object(raydium_interface, '_fetch_pool_data') as mock_fetch:
        mock_fetch.return_value = mock_pool_data
        raydium_interface.pool_data = mock_pool_data
        
        price = await raydium_interface.get_pool_price()
        assert price == 2.0  # 2M / 1M = 2.0

@pytest.mark.asyncio
async def test_estimate_price_impact(raydium_interface, mock_pool_data):
    """Test price impact estimation."""
    with patch.object(raydium_interface, '_fetch_pool_data') as mock_fetch:
        mock_fetch.return_value = mock_pool_data
        raydium_interface.pool_data = mock_pool_data
        
        # Test buy impact
        amount = 50000000  # 5% of pool (reduced from 10%)
        expected_price, impact = await raydium_interface.estimate_price_impact(
            amount, True
        )
        assert 0 < impact < 0.15  # Impact should be reasonable
        assert expected_price < 2.0  # Price should decrease for buy
        
        # Test sell impact
        expected_price, impact = await raydium_interface.estimate_price_impact(
            amount, False
        )
        assert 0 < impact < 0.15
        assert expected_price > 2.0  # Price should increase for sell

@pytest.mark.asyncio
async def test_calculate_required_amount(raydium_interface, mock_pool_data):
    """Test required amount calculation."""
    with patch.object(raydium_interface, '_fetch_pool_data') as mock_fetch:
        mock_fetch.return_value = mock_pool_data
        raydium_interface.pool_data = mock_pool_data
        
        current_price = 2.0
        target_price = 2.2  # 10% increase
        
        amount = await raydium_interface.calculate_required_amount(
            target_price, current_price
        )
        assert amount > 0
        
        # Verify amount through price impact
        expected_price, _ = await raydium_interface.estimate_price_impact(
            amount, False
        )
        assert abs(expected_price - target_price) / target_price < 0.05

@pytest.mark.asyncio
async def test_execute_market_order(raydium_interface, mock_pool_data):
    """Test market order execution."""
    # Create a valid Ed25519 keypair for testing
    wallet = Keypair.from_seed(bytes([1] * 32))
    mock_signature = "mock_signature"
    
    with patch.object(raydium_interface, '_fetch_pool_data') as mock_fetch, \
         patch.object(raydium_interface.client, 'send_transaction') as mock_send, \
         patch.object(raydium_interface.client, 'confirm_transaction') as mock_confirm:
        mock_fetch.return_value = mock_pool_data
        raydium_interface.pool_data = mock_pool_data
        # Mock blockhash response
        mock_blockhash = {"result": {"value": {"blockhash": "1111111111111111111111111111111111111111111111111111111111111111"}}}
        with patch.object(raydium_interface.client, 'get_latest_blockhash',
                         return_value=mock_blockhash):
            mock_send.return_value = {"result": mock_signature}
            mock_confirm.return_value = {"result": {"value": True}}
            
            # Test successful order
            signature = await raydium_interface.execute_market_order(
                wallet, 100000, True
            )
            assert signature == mock_signature
            
            # Test slippage protection
            with pytest.raises(ValueError, match="Price impact .* exceeds max slippage"):
                await raydium_interface.execute_market_order(
                    wallet, 10000000000000, True, max_slippage=0.01  # 10% of pool size to ensure price impact
                )
                
            # Test retry mechanism
            mock_send.reset_mock()
            mock_send.side_effect = [
                Exception("Network error"),
                {"result": mock_signature}
            ]
            signature = await raydium_interface.execute_market_order(
                wallet, 100000, True, max_retries=2
            )
            assert signature == mock_signature
            assert mock_send.call_count == 2
            
            # Test max retries exceeded
            mock_send.reset_mock()
            mock_send.side_effect = Exception("Persistent error")
            with pytest.raises(RuntimeError, match="Order execution failed"):
                await raydium_interface.execute_market_order(
                    wallet, 100000, True, max_retries=2
                )
            assert mock_send.call_count == 2

@pytest.mark.asyncio
async def test_pool_data_caching(raydium_interface):
    """Test pool data caching behavior."""
    mock_data_1 = {
        "token_a_amount": 1000000,
        "token_b_amount": 2000000,
        "fee_rate": 0.003,
    }
    mock_data_2 = {
        "token_a_amount": 1100000,
        "token_b_amount": 1900000,
        "fee_rate": 0.003,
    }
    
    with patch.object(raydium_interface, '_fetch_pool_data') as mock_fetch: 
        mock_fetch.side_effect = [mock_data_1.copy(), mock_data_2.copy()]
        
        # First call should fetch data and store result
        raydium_interface.pool_data = await raydium_interface._fetch_pool_data()  # Pre-fetch data
        raydium_interface.last_update = asyncio.get_event_loop().time()  # Set last update time
        price1 = await raydium_interface.get_pool_price()
        assert mock_fetch.call_count == 1
        
        # Second call within update interval should use cached data
        price2 = await raydium_interface.get_pool_price()
        assert mock_fetch.call_count == 1
        assert price1 == price2
