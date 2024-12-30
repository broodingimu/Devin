"""
Wallet management module for Solana market making bot.
Handles multiple hot wallets and their rotation for distributed trading.
"""
from typing import List, Dict, Optional, Set
import os
import logging
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solana.rpc.commitment import Confirmed

logger = logging.getLogger(__name__)

class WalletManager:
    def __init__(self, min_wallet_balance: float = 0.1):
        """
        Initialize wallet manager.
        
        Args:
            min_wallet_balance: Minimum SOL balance required for trading
        """
        load_dotenv()
        self.client = AsyncClient(os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"))
        self.wallets: Dict[str, Keypair] = {}
        self.wallet_balances: Dict[str, float] = {}
        self.min_wallet_balance = min_wallet_balance
        self.last_used: Dict[str, datetime] = {}
        self.transaction_history: Dict[str, List[Dict]] = {}
        self.cooldown_period = timedelta(minutes=5)  # Time to wait before reusing a wallet
        
        # Load and validate wallets
        self._load_wallets()
        if not self.wallets:
            raise ValueError("No valid wallets found in environment variables")

    def _load_wallets(self):
        """Load and validate wallet private keys from environment variables."""
        private_keys = os.getenv("WALLET_PRIVATE_KEYS", "").split(",")
        if not private_keys or not private_keys[0]:
            raise ValueError("No wallet private keys found in WALLET_PRIVATE_KEYS")

        for idx, private_key in enumerate(private_keys, 1):
            private_key = private_key.strip()
            # Validate private key format (32 bytes = 64 hex chars)
            if len(private_key) != 64:  # 32-byte key in hex = 64 hex chars
                logger.warning(f"Invalid private key length for wallet {idx}")
                continue
            
            try:
                secret_bytes = bytes.fromhex(private_key)
                if len(secret_bytes) != 32:
                    raise ValueError("Invalid private key length")
                keypair = Keypair.from_seed(secret_bytes)
                wallet_address = str(keypair.pubkey())
                self.wallets[wallet_address] = keypair
                self.transaction_history[wallet_address] = []
                logger.info(f"Loaded wallet {idx}: {wallet_address[:8]}...")
            except Exception as e:
                logger.error(f"Error creating keypair for wallet {idx}: {str(e)}")
                continue
    async def get_wallet_balance(self, public_key: str) -> float:
        """
        Get SOL balance for a specific wallet.
        
        Args:
            public_key: Wallet public key
            
        Returns:
            float: Balance in SOL
        """
        try:
            balance = await self.client.get_balance(self.wallets[public_key].pubkey(), commitment=Confirmed)
            sol_balance = float(balance.value) / 1e9
            self.wallet_balances[public_key] = sol_balance
            return sol_balance
        except Exception as e:
            logger.error(f"Error getting balance for {public_key[:8]}...: {str(e)}")
            return 0.0

    async def get_all_balances(self) -> Dict[str, float]:
        """
        Get balances for all managed wallets.
        
        Returns:
            Dict[str, float]: Mapping of wallet addresses to SOL balances
        """
        balances = {}
        for public_key in self.wallets:
            balances[public_key] = await self.get_wallet_balance(public_key)
        return balances

    async def get_available_wallets(self, required_balance: Optional[float] = None) -> List[Keypair]:
        """
        Get list of wallets available for trading.
        
        Args:
            required_balance: Minimum balance required for specific trade
            
        Returns:
            List[Keypair]: List of available wallet keypairs
        """
        min_balance = required_balance if required_balance else self.min_wallet_balance
        current_time = datetime.now()
        
        # Update all balances
        await self.get_all_balances()
        
        available_wallets = []
        for address, wallet in self.wallets.items():
            # Skip wallets in cooldown first
            if address in self.last_used:
                last_used = self.last_used[address]
                if (current_time - last_used) < self.cooldown_period:
                    logger.debug(f"Wallet {address[:8]}... in cooldown for {(current_time - last_used).total_seconds():.1f}s")
                    continue
            
            # Then check balance for non-cooldown wallets
            balance = self.wallet_balances.get(address, 0)
            logger.info(f"Checking wallet {address[:8]}... balance: {balance:.3f} SOL, required: {min_balance:.3f} SOL")
            if balance < min_balance:
                logger.debug(f"Wallet {address[:8]}... insufficient balance: {balance:.3f} SOL")
                continue
                
            available_wallets.append(wallet)
            
        return available_wallets

    def record_transaction(self, wallet_address: str, transaction_type: str, 
                         amount: float, timestamp: Optional[datetime] = None):
        """
        Record a transaction for a wallet.
        
        Args:
            wallet_address: Wallet public key
            transaction_type: Type of transaction (e.g., "BUY", "SELL")
            amount: Transaction amount in SOL
            timestamp: Transaction timestamp (default: current time)
        """
        if wallet_address not in self.transaction_history:
            self.transaction_history[wallet_address] = []
            
        tx_record = {
            "type": transaction_type,
            "amount": amount,
            "timestamp": timestamp or datetime.now().isoformat()
        }
        
        self.transaction_history[wallet_address].append(tx_record)
        self.last_used[wallet_address] = datetime.now()

    def get_wallet_history(self, wallet_address: str) -> List[Dict]:
        """
        Get transaction history for a specific wallet.
        
        Args:
            wallet_address: Wallet public key
            
        Returns:
            List[Dict]: List of transaction records
        """
        return self.transaction_history.get(wallet_address, [])

    async def close(self):
        """Clean up resources."""
        await self.client.close()
