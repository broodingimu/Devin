# Solana Market Making Bot

A market making bot for Solana blockchain, specifically designed for Raydium DEX. The bot manages multiple hot wallets to execute distributed trades for gradual price manipulation according to target price series.

## Setup

### Environment Configuration

1. Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```

2. Configure your Solana RPC URL and wallet private keys in `.env`:
```env
# Solana RPC URL (use a reliable provider)
SOLANA_RPC_URL=https://your-rpc-url.com

# Pool address for the target token
POOL_ADDRESS=your_pool_address_here

# Wallet private keys (add as many as needed)
# Each key should be a 64-byte hex string
WALLET_1=your_private_key_here
WALLET_2=your_private_key_here
WALLET_3=your_private_key_here
```

### Wallet Management

The bot uses multiple hot wallets to distribute trades and achieve gradual price movement. Key features:

- **Multiple Wallet Support**: Manages multiple Solana hot wallets for distributed trading
- **Balance Tracking**: Monitors SOL balances across all wallets
- **Transaction History**: Tracks all trades per wallet
- **Cooldown Period**: 5-minute cooldown between trades for each wallet
- **Minimum Balance**: Configurable minimum SOL balance requirement
- **Error Handling**: Robust error handling for wallet operations

### Installation

1. Install Poetry (Python package manager):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:
```bash
poetry install
```

## Architecture

### Components

1. **Wallet Management (`src/wallet_manager.py`)**
   - Manages multiple Solana hot wallets
   - Handles wallet rotation for distributed trading
   - Tracks wallet balances and transaction history

2. **Raydium DEX Interface (`src/raydium_interface.py`)**
   - Interacts with Raydium liquidity pools
   - Executes market orders
   - Calculates price impact and slippage

3. **Price Analysis (`src/price_analyzer.py`)**
   - Real-time price monitoring from pool contracts
   - Price impact estimation
   - Required SOL calculation for target prices

4. **Trade Distribution (`src/trade_distributor.py`)**
   - Implements gradual price movement strategy
   - Distributes trades across multiple wallets
   - Optimizes trade sizes for minimal cost

5. **CSV Processing (`src/csv_processor.py`)**
   - Reads target price series from CSV
   - Processes 5-minute interval data
   - Validates and schedules price targets

6. **Main Bot (`src/market_maker.py`)**
   - Orchestrates all components
   - Implements main trading loop
   - Handles error recovery and logging

### Dependencies
- `solana-py`: Solana blockchain interaction
- `pandas`: CSV processing
- `web3`: Smart contract interaction
- `python-dotenv`: Environment configuration
- `logging`: Logging functionality

### Configuration
- Wallet private keys stored in `.env`
- Target price series in CSV format
- Trading parameters configurable via config file

## Setup
[To be implemented]

## Usage
[To be implemented]
