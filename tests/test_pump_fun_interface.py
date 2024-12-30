import pytest
from unittest.mock import Mock, patch, AsyncMock
from solders.keypair import Keypair

from src.pump_fun_interface import PumpFunInterface
from src.pump_fun.bonding_curve_account import BondingCurveAccount

@pytest.fixture
def mock_bonding_curve():
    """Create a mock bonding curve with known reserves."""
    curve = Mock(spec=BondingCurveAccount)
    curve.virtual_token_reserves = 1_000_000 * 10**9  # 1M tokens
    curve.virtual_sol_reserves = 100 * 10**9  # 100 SOL
    curve.real_token_reserves = 800_000 * 10**9  # 800K tokens
    curve.real_sol_reserves = 80 * 10**9  # 80 SOL
    curve.get_token_price.return_value = 0.1  # 0.1 SOL per token
    return curve

@pytest.fixture
async def pump_fun_interface():
    """Create a PumpFunInterface instance with mocked dependencies."""
    interface = PumpFunInterface("TokenMintAddress")
    yield interface
    await interface.close()

@pytest.mark.asyncio
async def test_get_pool_price(pump_fun_interface, mock_bonding_curve):
    """Test getting current pool price."""
    with patch('src.pump_fun_interface.get_bonding_curve_account',
                     return_value=mock_bonding_curve):
        price = await pump_fun_interface.get_pool_price()
        assert price == 0.1
        mock_bonding_curve.get_token_price.assert_called_once()

@pytest.mark.asyncio
async def test_estimate_price_impact_buy(pump_fun_interface, mock_bonding_curve):
    """Test estimating price impact for buy orders."""
    amount = 10 * 10**9  # 10 SOL
    with patch('src.pump_fun_interface.get_bonding_curve_account',
                     return_value=mock_bonding_curve):
        impact = await pump_fun_interface.estimate_price_impact(amount, True)
        assert isinstance(impact, float)
        assert 0 <= impact <= 1  # Impact should be between 0-100%

@pytest.mark.asyncio
async def test_estimate_price_impact_sell(pump_fun_interface, mock_bonding_curve):
    """Test estimating price impact for sell orders."""
    amount = 10 * 10**9  # 10 SOL worth of tokens
    with patch('src.pump_fun_interface.get_bonding_curve_account',
                     return_value=mock_bonding_curve):
        impact = await pump_fun_interface.estimate_price_impact(amount, False)
        assert isinstance(impact, float)
        assert 0 <= impact <= 1  # Impact should be between 0-100%

@pytest.mark.asyncio
async def test_calculate_required_amount(pump_fun_interface, mock_bonding_curve):
    """Test calculating required amount for target price."""
    current_price = 0.1
    target_price = 0.12  # 20% increase
    with patch('src.pump_fun_interface.get_bonding_curve_account',
                     return_value=mock_bonding_curve):
        amount = await pump_fun_interface.calculate_required_amount(
            target_price, current_price
        )
        assert amount > 0  # Should require positive SOL amount for price increase

@pytest.mark.asyncio
async def test_execute_market_order(pump_fun_interface, mock_bonding_curve):
    """Test executing market order."""
    wallet = Keypair()
    amount = 1 * 10**9  # 1 SOL
    is_buy = True
    max_slippage = 0.01

    # Mock transaction creation and submission
    mock_tx = AsyncMock()
    mock_tx.return_value = "mock_signature"
    
    with patch('src.pump_fun_interface.get_bonding_curve_account',
                     return_value=mock_bonding_curve), \
            patch('src.pump_fun_interface.get_buy_instructions',
                  return_value=([], [])), \
            patch.object(pump_fun_interface, '_send_transaction', mock_tx):
        signature = await pump_fun_interface.execute_market_order(
            wallet, amount, is_buy, max_slippage
        )
        assert signature == "mock_signature"
        mock_tx.assert_called_once()

@pytest.mark.asyncio
async def test_execute_market_order_with_retry(pump_fun_interface, mock_bonding_curve):
    """Test market order execution with retry mechanism."""
    wallet = Keypair()
    amount = 1 * 10**9  # 1 SOL
    is_buy = True
    max_slippage = 0.01

    # Mock transaction that fails twice then succeeds
    mock_tx = AsyncMock()
    mock_tx.side_effect = [
        Exception("Transaction failed"),
        Exception("Transaction failed"),
        "success_signature"
    ]
    
    with patch('src.pump_fun_interface.get_bonding_curve_account',
                     return_value=mock_bonding_curve), \
            patch('src.pump_fun_interface.get_buy_instructions',
                  return_value=([], [])), \
            patch.object(pump_fun_interface, '_send_transaction', mock_tx):
        signature = await pump_fun_interface.execute_market_order(
            wallet, amount, is_buy, max_slippage
        )
        assert signature == "success_signature"
        assert mock_tx.call_count == 3  # Called three times due to retries
