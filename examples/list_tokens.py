from hyperliquid.info import Info
from hyperliquid.utils import constants
import json
from datetime import datetime

def main():
    # Initialize the Info client with testnet URL
    info = Info(constants.TESTNET_API_URL, skip_ws=True)
    
    # Get meta information which includes all listed tokens
    meta = info.meta()
    meta_and_ctx = info.meta_and_asset_ctxs()
    
    print("\nListed Perpetual Tokens:")
    print("-" * 50)
    for asset in meta["universe"]:
        print(f"Token: {asset['name']}")
        print(f"Decimals: {asset['szDecimals']}")
        if "maxLeverage" in asset:
            print(f"Max Leverage: {asset['maxLeverage']}x")
        if "onlyIsolated" in asset:
            print(f"Only Isolated: {asset['onlyIsolated']}")
        print("-" * 50)
    
    # Get detailed market information for each token
    print("\nDetailed Market Information:")
    print("=" * 80)
    for ctx in meta_and_ctx[1]:
        print(f"\nToken: {ctx['coin']}")
        if "markPx" in ctx and ctx["markPx"]:
            print(f"Mark Price: {ctx['markPx']}")
        if "midPx" in ctx and ctx["midPx"]:
            print(f"Mid Price: {ctx['midPx']}")
        if "openInterest" in ctx:
            print(f"Open Interest: {ctx['openInterest']}")
        if "dayNtlVlm" in ctx:
            print(f"24h Volume: {ctx['dayNtlVlm']}")
        if "funding" in ctx:
            print(f"Funding Rate: {ctx['funding']}")
        print("-" * 50)

    # Get all current mid prices
    all_mids = info.all_mids()
    print("\nCurrent Mid Prices:")
    print("-" * 50)
    for coin, price in all_mids.items():
        print(f"{coin}: {price}")

if __name__ == "__main__":
    main()
