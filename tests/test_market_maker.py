"""
Unit tests for market maker module.
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta

from src.market_maker import MarketMaker
from src.wallet_manager import WalletManager
from src.raydium_interface import RaydiumInterface
from src.trade_distributor import TradeDistributor
from src.csv_processor import CSVProcessor

@pytest.fixture
def mock_wallet_manager():
    """Create a mock wallet manager."""
    manager = Mock(spec=WalletManager)
    manager.close = AsyncMock()
    return manager

@pytest.fixture
def mock_raydium():
    """Create a mock Raydium interface."""
    raydium = Mock(spec=RaydiumInterface)
    raydium.get_pool_price = AsyncMock(return_value=1.0)
    raydium.close = AsyncMock()
    return raydium

@pytest.fixture
def mock_trade_distributor():
    """Create a mock trade distributor."""
    distributor = Mock(spec=TradeDistributor)
    distributor.calculate_trade_distribution = AsyncMock()
    distributor.execute_trades = AsyncMock()
    distributor.min_trade_size = 0.1  # Add min_trade_size attribute
    return distributor

@pytest.fixture
def mock_csv_processor():
    """Create a mock CSV processor."""
    processor = Mock(spec=CSVProcessor)
    processor.load_price_data = Mock()
    processor.get_next_target = AsyncMock()
    processor.get_remaining_targets = Mock()
    return processor

@pytest.fixture
def market_maker(
    mock_wallet_manager, mock_raydium, mock_trade_distributor, mock_csv_processor
):
    """Create a market maker with mock dependencies."""
    with patch('src.market_maker.WalletManager') as wm_mock, \
         patch('src.market_maker.RaydiumInterface') as ri_mock, \
         patch('src.market_maker.TradeDistributor') as td_mock, \
         patch('src.market_maker.CSVProcessor') as cp_mock:
        
        wm_mock.return_value = mock_wallet_manager
        ri_mock.return_value = mock_raydium
        td_mock.return_value = mock_trade_distributor
        cp_mock.return_value = mock_csv_processor
        
        maker = MarketMaker(
            pool_address="pool123",
            csv_path="prices.csv",
            max_slippage=0.01,
            min_trade_size=0.1,
            max_trade_size=1.0,
            max_trades_per_interval=5
        )
        return maker


@pytest.mark.asyncio
async def test_start_and_stop(market_maker):
    """Test starting and stopping the market maker."""
    # Setup mock
    market_maker.csv_processor.get_remaining_targets.return_value = 0
    
    # Start market maker
    await market_maker.start()
    assert market_maker.running == False  # Should stop when no targets remain
    
    # Stop market maker
    await market_maker.stop()
    assert market_maker.running == False
    
    # Verify cleanup was called
    assert market_maker.wallet_manager.close.await_count == 1
    assert market_maker.raydium.close.await_count == 1

@pytest.mark.asyncio
async def test_price_manipulation_loop(market_maker):
    """Test the main price manipulation loop."""
    # Setup mocks with enough values for multiple loop iterations and cleanup
    market_maker.csv_processor.get_remaining_targets.side_effect = [1, 0]  # One trade then done
    market_maker.csv_processor.get_next_target.return_value = (1.5, datetime.now())
    market_maker.raydium.get_pool_price.return_value = 1.0
    market_maker.trade_distributor.calculate_trade_distribution.return_value = [
        (Mock(), 0.5, True)
    ]
    market_maker.trade_distributor.execute_trades.return_value = ["sig1"]
    
    # Ensure running is set to True initially
    market_maker.running = True
    
    # Run market maker
    await market_maker.start()
    
    # Verify price manipulation was attempted
    assert market_maker.trade_distributor.calculate_trade_distribution.await_count == 1
    assert market_maker.trade_distributor.execute_trades.await_count == 1

@pytest.mark.asyncio
async def test_error_handling(market_maker):
    """Test error handling in price manipulation loop."""
    # Setup mock to raise an error and then complete
    market_maker.csv_processor.get_remaining_targets.side_effect = [1, 0]  # One error then done
    market_maker.csv_processor.get_next_target.return_value = (1.5, datetime.now())  # Ensure valid tuple first
    market_maker.raydium.get_pool_price.side_effect = Exception("Network error")
    
    # Run market maker
    await market_maker.start()
    
    # Verify error was caught and stored
    assert market_maker.last_error is not None
    assert isinstance(market_maker.last_error, str)
    assert "Network error" in str(market_maker.last_error)
    assert market_maker.running == False  # Verify market maker stopped
    
    # Verify cleanup was called
    assert market_maker.wallet_manager.close.await_count == 1
    assert market_maker.raydium.close.await_count == 1

@pytest.mark.asyncio
async def test_price_already_at_target(market_maker):
    """Test behavior when price is already at target."""
    # Setup mocks with enough values for multiple loop iterations and cleanup
    market_maker.csv_processor.get_remaining_targets.side_effect = [1, 1, 1, 1, 1, 1, 1, 0, 0]  # Extra 0 for cleanup check
    market_maker.csv_processor.get_next_target.return_value = (1.0, datetime.now())
    market_maker.raydium.get_pool_price.return_value = 1.0
    
    # Run market maker
    await market_maker.start()
    
    # Verify no trades were attempted
    assert market_maker.trade_distributor.calculate_trade_distribution.await_count == 0
    assert market_maker.trade_distributor.execute_trades.await_count == 0

@pytest.mark.asyncio
async def test_gradual_price_movement(market_maker):
    """Test gradual price movement with distributed trades."""
    # Setup mocks for a single trade cycle
    market_maker.csv_processor.get_remaining_targets.side_effect = [1, 0]  # One trade then done
    market_maker.csv_processor.get_next_target.return_value = (2.0, datetime.now())  # 100% increase
    market_maker.raydium.get_pool_price.return_value = 1.0
    
    # Ensure running is set to True initially
    market_maker.running = True
    
    # Mock trade distribution calculation
    trades = [
        (Mock(), 0.2, True),  # Small trades from different wallets
        (Mock(), 0.2, True),
        (Mock(), 0.2, True),
        (Mock(), 0.2, True),
        (Mock(), 0.2, True)
    ]
    market_maker.trade_distributor.calculate_trade_distribution.return_value = trades
    market_maker.trade_distributor.execute_trades.return_value = [f"sig{i}" for i in range(5)]
    
    # Run market maker
    await market_maker.start()
    
    # Verify trades were distributed
    assert market_maker.trade_distributor.calculate_trade_distribution.await_count == 1
    assert market_maker.trade_distributor.execute_trades.await_count == 1
    
    # Verify trade distribution parameters
    market_maker.trade_distributor.calculate_trade_distribution.assert_called_with(
        target_price=2.0,
        current_price=1.0,
        max_slippage=market_maker.max_slippage)
    # Verify trade size constraints through mock calls
    assert market_maker.trade_distributor.execute_trades.called

@pytest.mark.asyncio
async def test_slippage_handling(market_maker):
    """Test slippage handling in trade execution."""
    # Setup mocks for a single trade cycle
    market_maker.csv_processor.get_remaining_targets.side_effect = [1, 0]  # One trade then done
    market_maker.csv_processor.get_next_target.return_value = (1.5, datetime.now())
    market_maker.raydium.get_pool_price.return_value = 1.0
    
    # Ensure running is set to True initially
    market_maker.running = True
    
    # Mock price impact calculation
    async def get_price_impact(amount):
        return 0.015 if amount > 0.5 else 0.005  # 1.5% impact for large trades
    
    market_maker.raydium.get_price_impact = AsyncMock(side_effect=get_price_impact)
    
    # Mock trade distribution to test slippage
    trades = [(Mock(), 0.4, True)]  # Smaller trade to stay within slippage
    market_maker.trade_distributor.calculate_trade_distribution.return_value = trades
    market_maker.trade_distributor.execute_trades.return_value = ["sig1"]
    
    # Run market maker
    await market_maker.start()
    
    # Verify slippage constraints were respected
    market_maker.trade_distributor.calculate_trade_distribution.assert_called_with(
        target_price=1.5,
        current_price=1.0,
        max_slippage=market_maker.max_slippage)
    # Verify trades were executed
    assert market_maker.trade_distributor.execute_trades.called
