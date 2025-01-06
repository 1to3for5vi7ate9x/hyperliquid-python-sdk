from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.error import ServerError, ClientError
from hyperliquid.exchange import Exchange
import json
import time
from datetime import datetime
import os
import logging
from typing import Dict, Any, Optional, List
from collections import deque
from time import time, sleep
from dataclasses import dataclass
from enum import Enum
import requests
import json
import asyncio
from threading import Thread
from queue import Queue
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
env_path = Path(__file__).resolve().parents[1] / '.env'
load_dotenv(dotenv_path=env_path)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class AlertType(Enum):
    PRICE_CHANGE = "PRICE_CHANGE"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    FUNDING_RATE = "FUNDING_RATE"
    OI_CHANGE = "OI_CHANGE"

@dataclass
class MarketAlert:
    type: AlertType
    token: str
    message: str
    value: float
    threshold: float
    timestamp: int

class MonitorWallet:
    """Simple wallet for monitoring only"""
    def sign_message(self, msg):
        return "0x" + "0" * 130

    def get_address(self):
        return "0x" + "0" * 40

    def get_chain_id(self):
        return 1

class NotificationConfig:
    def __init__(self, discord_webhook_url: Optional[str] = None):
        self.discord_webhook_url = discord_webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        
    def send_discord_message(self, content: str, embeds: List[Dict] = None):
        if not self.discord_webhook_url:
            return
            
        try:
            data = {"content": content}
            if embeds:
                data["embeds"] = embeds
                
            response = requests.post(
                self.discord_webhook_url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Failed to send Discord notification: {e}")
            
    def send_new_token_alert(self, token: Dict):
        if not self.discord_webhook_url:
            return
            
        embed = {
            "title": f"🆕 New Token Listed: {token['name']}",
            "color": 3447003,  # Blue
            "fields": [
                {"name": "💰 Current Price", "value": f"${token['price']:.4f}", "inline": True},
                {"name": "📊 Initial Open Interest", "value": f"${token['openInterest']:,.2f}", "inline": True},
                {"name": "📈 Mark Price", "value": f"${token['markPrice']:.4f}", "inline": True},
                {"name": "💫 24h Volume", "value": f"${token['dayVolume']:,.2f}", "inline": True},
                {"name": "💸 Funding Rate", "value": f"{token['funding']*100:.4f}%", "inline": True},
                {"name": "⚡ Max Leverage", "value": f"{token['maxLeverage']}x", "inline": True},
                {"name": "🔢 Decimals", "value": str(token['decimals']), "inline": True},
                {"name": "🔒 Only Isolated", "value": str(token['onlyIsolated']), "inline": True}
            ],
            "timestamp": datetime.fromtimestamp(token['listing_time']/1000).isoformat()
        }
        
        self.send_discord_message("", [embed])
        
    def send_market_alert(self, alert: MarketAlert):
        if not self.discord_webhook_url:
            return
            
        colors = {
            AlertType.PRICE_CHANGE: 3447003,  # Blue
            AlertType.VOLUME_SPIKE: 10181046,  # Purple
            AlertType.FUNDING_RATE: 15844367,  # Yellow
            AlertType.OI_CHANGE: 3066993,  # Green
        }
        
        emojis = {
            AlertType.PRICE_CHANGE: "💰",
            AlertType.VOLUME_SPIKE: "📊",
            AlertType.FUNDING_RATE: "💸",
            AlertType.OI_CHANGE: "📈"
        }
        
        embed = {
            "title": f"{emojis.get(alert.type, '⚠️')} Market Alert: {alert.token}",
            "description": alert.message,
            "color": colors.get(alert.type, 0),
            "fields": [
                {"name": "Type", "value": alert.type.value, "inline": True},
                {"name": "Value", "value": f"{alert.value:.2f}%", "inline": True},
                {"name": "Threshold", "value": f"{alert.threshold:.2f}%", "inline": True}
            ],
            "timestamp": datetime.fromtimestamp(alert.timestamp/1000).isoformat()
        }
        
        self.send_discord_message("", [embed])

class WebSocketManager:
    def __init__(self, notification_config: 'NotificationConfig', market_monitor: 'MarketMonitor'):
        self.notification_config = notification_config
        self.market_monitor = market_monitor
        self.monitor_wallet = MonitorWallet()
        self.info = Info(constants.MAINNET_API_URL)  # Use Info class for WebSocket
        self.price_updates = Queue()
        self.running = True
        
    def start(self):
        # Start price update processor
        self.process_thread = Thread(target=self.process_price_updates, daemon=True)
        self.process_thread.start()
        
        # Subscribe to trades for all coins
        self.info.subscribe({"type": "allMids"}, self.handle_price_update)
        
    def stop(self):
        self.running = False
        if hasattr(self, 'process_thread'):
            self.process_thread.join(timeout=1)
            
    def handle_price_update(self, data):
        try:
            if isinstance(data, dict) and 'data' in data:
                for update in data['data']:
                    if isinstance(update, dict) and 'coin' in update and 'mid' in update:
                        self.price_updates.put((update['coin'], float(update['mid'])))
        except Exception as e:
            logging.error(f"Error processing price update: {e}")
                
    def process_price_updates(self):
        while self.running:
            try:
                while not self.price_updates.empty():
                    coin, price = self.price_updates.get()
                    # Update market monitor with new price
                    alerts = self.market_monitor.update_price(coin, price)
                    
                    # Send alerts if any
                    for alert in alerts:
                        print_market_alert(alert)
                        self.notification_config.send_market_alert(alert)
                        
                sleep(0.1)
            except Exception as e:
                logging.error(f"Error processing price updates: {e}")
                sleep(1)

class MarketMonitor:
    def __init__(self, 
                 price_change_threshold: Optional[float] = None,
                 volume_spike_threshold: Optional[float] = None,
                 funding_rate_threshold: Optional[float] = None,
                 oi_change_threshold: Optional[float] = None):
        # Load thresholds from environment variables or use defaults
        self.price_change_threshold = price_change_threshold or float(os.getenv('PRICE_CHANGE_THRESHOLD', 1.0))
        self.volume_spike_threshold = volume_spike_threshold or float(os.getenv('VOLUME_SPIKE_THRESHOLD', 200.0))
        self.funding_rate_threshold = funding_rate_threshold or float(os.getenv('FUNDING_RATE_THRESHOLD', 0.1))
        self.oi_change_threshold = oi_change_threshold or float(os.getenv('OI_CHANGE_THRESHOLD', 100.0))
        self.token_data = {}
        
    def update_price(self, token: str, price: float) -> List[MarketAlert]:
        alerts = []
        now = int(time() * 1000)
        
        if token not in self.token_data:
            self.token_data[token] = {
                'first_price': price,
                'last_price': price,
                'price_history': [(now, price)],
                'last_alert_time': 0
            }
            return alerts
            
        token_history = self.token_data[token]
        
        # Don't alert more than once per minute for the same token
        if now - token_history.get('last_alert_time', 0) < 60000:
            return alerts
            
        # Price change monitoring
        price_change_pct = ((price - token_history['first_price']) / token_history['first_price']) * 100
        if abs(price_change_pct) >= self.price_change_threshold:
            alerts.append(MarketAlert(
                type=AlertType.PRICE_CHANGE,
                token=token,
                message=f"Price {'increased' if price_change_pct > 0 else 'decreased'} by {abs(price_change_pct):.2f}% since listing (Current: ${price:.4f})",
                value=price_change_pct,
                threshold=self.price_change_threshold,
                timestamp=now
            ))
            token_history['last_alert_time'] = now
            
        # Update history
        token_history['last_price'] = price
        token_history['price_history'].append((now, price))
        
        # Keep last 24 hours of data
        ONE_DAY = 24 * 60 * 60 * 1000
        while token_history['price_history'] and now - token_history['price_history'][0][0] > ONE_DAY:
            token_history['price_history'].pop(0)
                
        return alerts

class TokenState:
    def __init__(self, token_file='known_tokens.json'):
        self.token_file = token_file
        self.tokens: Dict[str, Dict] = self.load_tokens()
        self.market_monitor = MarketMonitor()

    def load_tokens(self) -> Dict:
        try:
            with open(self.token_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_tokens(self):
        with open(self.token_file, 'w') as f:
            json.dump(self.tokens, f, indent=2)

    def update_tokens(self, current_tokens: Dict[str, Dict]) -> List[Dict]:
        new_tokens = []
        all_alerts = []
        current_time = int(time() * 1000)
        
        for token, info in current_tokens.items():
            is_new = False
            if token not in self.tokens:
                is_new = True
                logging.info(f"Found completely new token: {token}")
            elif self.tokens[token].get('status') == 'pending' and info.get('status') == 'active':
                is_new = True
                logging.info(f"Token {token} has been activated")
            elif self.tokens[token].get('initial_oi', -1) == -1:
                is_new = True
            
            if is_new:
                current_oi = float(info.get('openInterest', 0))
                # Consider a token as new if:
                # 1. It has pending status (newly listed)
                # 2. OR it has active status with OI <= 50000
                if info.get('status') == 'pending' or current_oi <= 50000:
                    info['initial_oi'] = current_oi
                    info['listing_time'] = current_time
                    new_tokens.append({
                        'name': token,
                        **info
                    })
                    logging.info(f"New token detected - Name: {token}, Status: {info.get('status')}, OI: {current_oi}")
            
            # Update token info and get market alerts
            if token in self.tokens:
                current_info = self.tokens[token].copy()
                current_info.update(info)
                self.tokens[token] = current_info
                
                # Only monitor market conditions for active tokens
                if info.get('status') == 'active':
                    alerts = self.market_monitor.update(token, info)
                    if alerts:
                        all_alerts.extend(alerts)
            else:
                info['last_updated'] = current_time
                self.tokens[token] = info.copy()
                # Initialize market monitoring for active tokens
                if info.get('status') == 'active':
                    self.market_monitor.update(token, info)
        
        self.save_tokens()
        return new_tokens, all_alerts

class WeightedRateLimiter:
    def __init__(self, max_weight: int, time_window: float):
        self.max_weight = max_weight
        self.time_window = time_window
        self.requests = deque()
        self.current_weight = 0

    def wait(self, weight: int):
        now = time()
        
        while self.requests and self.requests[0][0] < now - self.time_window:
            _, old_weight = self.requests.popleft()
            self.current_weight -= old_weight
        
        while self.current_weight + weight > self.max_weight and self.requests:
            sleep_time = self.requests[0][0] + self.time_window - now
            if sleep_time > 0:
                logging.info(f"Rate limit reached (current weight: {self.current_weight}, adding: {weight}), waiting {sleep_time:.2f} seconds...")
                sleep(sleep_time)
            now = time()
            _, old_weight = self.requests.popleft()
            self.current_weight -= old_weight
        
        self.requests.append((now, weight))
        self.current_weight += weight

def get_all_mids(info_client: Info, rate_limiter: WeightedRateLimiter) -> Optional[Dict]:
    rate_limiter.wait(2)
    try:
        response = info_client.post("/info", {"type": "allMids"})
        if isinstance(response, dict):
            return response
        logging.error(f"Unexpected all_mids response format: {response}")
        return None
    except (ServerError, ClientError) as e:
        logging.error(f"API error fetching all_mids: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching all_mids: {e}")
        return None

def initialize_api(rate_limiter: WeightedRateLimiter, max_retries: int = 5, retry_delay: int = 5) -> Optional[Info]:
    for attempt in range(max_retries):
        try:
            info = Info(constants.MAINNET_API_URL, skip_ws=True)
            response = info.meta_and_asset_ctxs()
            if not isinstance(response, list) or len(response) != 2:
                raise Exception("Failed to get initial meta data")
            return info
        except Exception as e:
            logging.error(f"Error during initialization (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                sleep(retry_delay)
                continue
    return None

def get_token_info(info_client: Info, rate_limiter: WeightedRateLimiter) -> Optional[Dict]:
    try:
        # Get meta and asset contexts which includes all info we need
        response = info_client.meta_and_asset_ctxs()
        if not isinstance(response, list) or len(response) != 2:
            logging.error(f"Unexpected meta_and_asset_ctxs response format: {response}")
            return None

        meta, asset_ctxs = response
        if not isinstance(meta, dict) or 'universe' not in meta:
            logging.error(f"Invalid meta format: {meta}")
            return None

        # Get current prices
        all_mids = get_all_mids(info_client, rate_limiter)
        if all_mids is None:
            all_mids = {}  # Continue even without prices
            
        tokens = {}
        for coin in meta['universe']:
            name = coin['name']
            # Find matching asset context, but don't require it
            asset_ctx = next((ctx for ctx in asset_ctxs if isinstance(ctx, dict) and ctx.get('coin') == name), {})
            
            # Include the token even if it doesn't have all data
            tokens[name] = {
                'maxLeverage': coin.get('maxLeverage', 'N/A'),
                'onlyIsolated': coin.get('onlyIsolated', False),
                'decimals': coin.get('szDecimals', 0),
                'price': float(all_mids.get(name, 0)),
                'openInterest': float(asset_ctx.get('openInterest', 0)),
                'markPrice': float(asset_ctx.get('markPx', 0)),
                'dayVolume': float(asset_ctx.get('dayNtlVlm', 0)),
                'funding': float(asset_ctx.get('funding', 0)),
                'last_updated': int(time() * 1000),
                'status': 'active' if asset_ctx else 'pending'  # Track if token is fully active
            }
            
            # Log new tokens that don't have asset contexts yet
            if not asset_ctx:
                logging.info(f"Found potentially new token: {name} (pending activation)")
                
        return tokens
    except Exception as e:
        logging.error(f"Error getting token info: {e}")
        return None

def print_token_info(token: Dict):
    print("\n" + "=" * 80)
    print(f" NEW TOKEN LISTED: {token['name']}")
    print("-" * 80)
    print(f" Current Price: ${token['price']:.4f}")
    print(f" Initial Open Interest: ${token['openInterest']:,.2f}")
    print(f" Mark Price: ${token['markPrice']:.4f}")
    print(f" 24h Volume: ${token['dayVolume']:,.2f}")
    print(f" Funding Rate: {token['funding']*100:.4f}%")
    print(f" Max Leverage: {token['maxLeverage']}x")
    print(f" Decimals: {token['decimals']}")
    print(f" Only Isolated: {token['onlyIsolated']}")
    print(f" Listed at: {datetime.fromtimestamp(token['listing_time']/1000).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80 + "\n")

def print_market_alert(alert: MarketAlert):
    alert_colors = {
        AlertType.PRICE_CHANGE: "",
        AlertType.VOLUME_SPIKE: "",
        AlertType.FUNDING_RATE: "",
        AlertType.OI_CHANGE: ""
    }
    
    color = alert_colors.get(alert.type, "")
    print(f"\n{color} MARKET ALERT: {alert.token}")
    print("-" * 60)
    print(f"Type: {alert.type.value}")
    print(f"Message: {alert.message}")
    print(f"Time: {datetime.fromtimestamp(alert.timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60 + "\n")

def main():
    logging.info("Starting new token listing monitor at %s", datetime.now())
    
    # Load configuration from environment
    discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not discord_webhook_url:
        logging.warning("DISCORD_WEBHOOK_URL not set in .env file. Notifications will only be shown in console.")
    notification_config = NotificationConfig(discord_webhook_url)
    
    # Load thresholds from environment
    price_threshold = float(os.getenv('PRICE_CHANGE_THRESHOLD', 1.0))
    volume_threshold = float(os.getenv('VOLUME_SPIKE_THRESHOLD', 200.0))
    funding_threshold = float(os.getenv('FUNDING_RATE_THRESHOLD', 0.1))
    oi_threshold = float(os.getenv('OI_CHANGE_THRESHOLD', 100.0))
    
    print("\n" + "=" * 80)
    print("🔍 MONITORING FOR NEW TOKEN LISTINGS AND MARKET ACTIVITY")
    print("=" * 80)
    print("\n📊 Market Alert Thresholds:")
    print(f"- Price Change: ±{price_threshold}%")
    print(f"- Volume Spike: {volume_threshold}%")
    print(f"- Funding Rate: ±{funding_threshold}%")
    print(f"- Open Interest: {oi_threshold}%")
    if discord_webhook_url:
        print("\n🔔 Discord notifications enabled!")
    print("\n📡 WebSocket enabled for real-time price updates")
    print("\nPress Ctrl+C to stop monitoring\n")
    print("=" * 80 + "\n")

    rate_limiter = WeightedRateLimiter(max_weight=1200, time_window=60)
    token_state = TokenState()
    market_monitor = MarketMonitor(
        price_change_threshold=price_threshold,
        volume_spike_threshold=volume_threshold,
        funding_rate_threshold=funding_threshold,
        oi_change_threshold=oi_threshold
    )
    
    info = initialize_api(rate_limiter)
    if info is None:
        logging.error("Failed to initialize API after multiple retries")
        return

    # Initialize and start WebSocket
    ws_manager = WebSocketManager(notification_config, market_monitor)
    ws_manager.start()
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    try:
        while True:
            try:
                current_tokens = get_token_info(info, rate_limiter)
                if current_tokens is None:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logging.error("Too many consecutive errors. Exiting...")
                        break
                    continue

                consecutive_errors = 0

                # Check for new tokens and market alerts
                new_tokens, alerts = token_state.update_tokens(current_tokens)
                
                # Handle new tokens
                for token in new_tokens:
                    print_token_info(token)
                    notification_config.send_new_token_alert(token)
                    logging.info(f"New token detected: {token['name']} with initial OI: {token['openInterest']}")

                # Handle market alerts
                for alert in alerts:
                    print_market_alert(alert)
                    notification_config.send_market_alert(alert)

            except Exception as e:
                logging.error(f"Error in main loop: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logging.error("Too many consecutive errors. Exiting...")
                    break
                sleep(5)
                continue

            sleep(5)

    except KeyboardInterrupt:
        logging.info("\nStopping monitoring...")
        ws_manager.stop()
        token_state.save_tokens()

if __name__ == "__main__":
    main()
