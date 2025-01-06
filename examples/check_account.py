from hyperliquid.info import Info
from hyperliquid.utils import constants
import json

def main():
    # Initialize the Info client with testnet URL
    info = Info(constants.TESTNET_API_URL, skip_ws=True)
    
    # Load config
    with open('examples/config.json', 'r') as f:
        config = json.load(f)
    
    account_address = config['account_address']
    print(f"\nChecking account: {account_address}")
    
    # Get user state
    try:
        user_state = info.user_state(account_address)
        print("\nUser State:")
        print(json.dumps(user_state, indent=2))
    except Exception as e:
        print(f"Error getting user state: {e}")
    
    # Get all user states
    try:
        all_user_states = info.all_user_states(account_address)
        print("\nAll User States:")
        print(json.dumps(all_user_states, indent=2))
    except Exception as e:
        print(f"Error getting all user states: {e}")
    
    # Get user fills
    try:
        user_fills = info.user_fills(account_address)
        print("\nUser Fills:")
        print(json.dumps(user_fills, indent=2))
    except Exception as e:
        print(f"Error getting user fills: {e}")

if __name__ == "__main__":
    main()
