"""Constants for pump.fun integration."""
from solders.pubkey import Pubkey

# Program ID for pump.fun
PUMP_FUN_PROGRAM = Pubkey.from_string("PFUNKqKhYWM1xvdqEE41PFW5qGTA5rkP3FS2Th9LvQK")

# Decimals for SOL and token amounts
SOL_DECIMAL = 9
TOKEN_DECIMAL = 9

# System program ID
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

# Token program constants
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
