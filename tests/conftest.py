"""Pytest configuration and fixtures."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables for testing."""
    os.environ['WALLET_PRIVATE_KEYS'] = 'mock_private_key_1,mock_private_key_2'
    os.environ['RPC_ENDPOINT'] = 'https://api.mainnet-beta.solana.com'
    yield
    del os.environ['WALLET_PRIVATE_KEYS']
    del os.environ['RPC_ENDPOINT']
