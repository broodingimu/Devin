"""
Unit tests for trade distributor module.
"""
import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from src.trade_distributor import TradeDistributor
from src.wallet_manager import WalletManager
from src.raydium_interface import RaydiumInterface

@pytest.fixture
def mock_wallet_manager():
    """Create a mock wallet manager."""
    manager = Mock(spec=WalletManager)
    mock_wallets = []
    for i, balance in enumerate([1.0, 1.5, 0.8, 2.0, 1.2]):
        wallet = Mock()
        wallet.balance = balance
        wallet.last_trade = None
        wallet.pubkey = lambda: f"wallet_{i}"
        wallet.execute_trade = AsyncMock(return_value=f"sig_{i}")
        mock_wallets.append(wallet)
    manager.get_available_wallets = AsyncMock(return_value=mock_wallets)
    return manager

@pytest.fixture
def mock_raydium():
    """Create a mock Raydium interface."""
    raydium = Mock(spec=RaydiumInterface)
    raydium.get_price_impact = AsyncMock(return_value=0.005)  # 0.5% impact
    raydium.calculate_required_amount = AsyncMock(return_value=0.5)  # Return float for amount calculation
    return raydium

@pytest.fixture
def trade_distributor(mock_wallet_manager, mock_raydium):
    """Create a trade distributor with mock dependencies."""
    distributor = TradeDistributor(
        wallet_manager=mock_wallet_manager,
        raydium=mock_raydium,
        min_trade_size=0.1,
        max_trade_size=1.0,
        max_trades_per_interval=5
    )
    # Set up mock attributes
    distributor.max_trade_size = 1.0
    return distributor

@pytest.mark.asyncio
async def test_calculate_trade_distribution(trade_distributor):
    """Test trade distribution calculation."""
    current_price = 1.0
    target_price = 1.5  # 50% increase
    
    trades = await trade_distributor.calculate_trade_distribution(
        target_price=target_price,
        current_price=current_price,
        max_slippage=0.01
    )
    
    # Verify trade distribution
    assert len(trades) > 0
    assert len(trades) <= trade_distributor.max_trades_per_interval
    
    # Verify trade sizes
    for wallet, amount, is_buy in trades:
        assert amount >= trade_distributor.min_trade_size
        assert amount <= trade_distributor.max_trade_size
        assert is_buy  # Should be buying to increase price

@pytest.mark.asyncio
async def test_execute_trades(trade_distributor):
    """Test trade execution."""
    # Setup mock trades with proper wallet mocks
    mock_trades = []
    for i, amount in enumerate([0.5, 0.3, 0.4]):
        wallet = Mock()
        wallet.balance = amount * 2  # Ensure sufficient balance
        wallet.pubkey = lambda: f"wallet_{i}"
        wallet.execute_trade = AsyncMock(return_value=f"sig_{i}")
        mock_trades.append((wallet, amount, True))
    
    signatures = await trade_distributor.execute_trades(mock_trades)
    
    # Verify all trades were executed
    assert len(signatures) == len(mock_trades)
    assert all(sig is not None for sig in signatures)
    
    # Verify each wallet's execute_trade was called
    for (wallet, amount, is_buy), sig in zip(mock_trades, signatures):
        wallet.execute_trade.assert_called_once()
        assert sig in [f"sig_{i}" for i in range(3)]

@pytest.mark.asyncio
async def test_slippage_constraint(trade_distributor):
    """Test slippage constraints in trade distribution."""
    # Setup high price impact
    trade_distributor.raydium.get_price_impact.return_value = 0.02  # 2% impact
    
    trades = await trade_distributor.calculate_trade_distribution(
        target_price=1.5,
        current_price=1.0,
        max_slippage=0.01  # 1% max slippage
    )
    
    # Verify trades respect slippage
    assert all(amount <= 0.5 for _, amount, _ in trades)  # Smaller trades to reduce impact

@pytest.mark.asyncio
async def test_wallet_selection(trade_distributor):
    """Test wallet selection for trades."""
    trades = await trade_distributor.calculate_trade_distribution(
        target_price=1.2,
        current_price=1.0,
        max_slippage=0.01
    )
    
    # Verify wallet selection
    wallets = [wallet for wallet, _, _ in trades]
    assert len(set(wallets)) == len(wallets)  # All wallets should be unique
    
    # Verify wallet balance constraints
    for wallet, amount, _ in trades: 
        assert hasattr(wallet, 'balance')
        assert wallet.balance >= amount  # Trade amount within wallet balance
