from dashboard.app import update_universe
import json

update_universe("SOL/USD", {"STRUCTURAL": True, "LIQUIDITY_SMC": False}, "CRYPTO_ALT", "run_test_002")

print("Universe update executed.")
