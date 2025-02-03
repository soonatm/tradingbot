import requests
import time
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime
import json
from telegram import Bot
from telegram.error import TelegramError
from app import logs  # Import logs from the Flask app

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

# Constants
DEXSCREENER_API_URL = config["dex_screener_api_url"]
POCKET_UNIVERSE_API_URL = config["pocket_universe_api_url"]
POCKET_UNIVERSE_API_KEY = config["pocket_universe_api_key"]
RUGCHECK_API_URL = config["rugcheck_api_url"]
DATABASE_URI = config["database_uri"]
UPDATE_INTERVAL = config["update_interval"]
FILTERS = config["filters"]
BLACKLIST = config["blacklist"]
TELEGRAM_BOT_TOKEN = config["telegram"]["bot_token"]
TELEGRAM_CHAT_ID = config["telegram"]["chat_id"]
BONKBOT_TOKEN = config["telegram"]["bonkbot_token"]

# Database setup
engine = create_engine(DATABASE_URI)

# Telegram bot setup
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

def send_telegram_message(message):
    """Send a message via Telegram."""
    try:
        telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except TelegramError as e:
        logs.append(f"Failed to send Telegram message: {e}")

def execute_bonkbot_trade(action, token_address, amount):
    """Execute a trade via BonkBot."""
    command = f"/{action} {token_address} {amount}"
    try:
        telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=command)
        logs.append(f"Sent BonkBot command: {command}")
    except TelegramError as e:
        logs.append(f"Failed to execute BonkBot trade: {e}")

def fetch_token_data(token_address):
    """Fetch token data from DexScreener API."""
    url = f"{DEXSCREENER_API_URL}{token_address}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logs.append(f"Failed to fetch data for token {token_address}")
        return None

def parse_token_data(token_data):
    """Parse token data to extract relevant metrics."""
    if not token_data:
        return None

    token_info = token_data.get("pairs", [{}])[0]
    return {
        "timestamp": datetime.now(),
        "token_address": token_info.get("baseToken", {}).get("address"),
        "token_name": token_info.get("baseToken", {}).get("name"),
        "price_usd": token_info.get("priceUsd"),
        "volume_24h": token_info.get("volume", {}).get("h24"),
        "liquidity_usd": token_info.get("liquidity", {}).get("usd"),
        "market_cap_usd": token_info.get("fdv"),
        "chain": token_info.get("chainId"),
        "dev_address": token_info.get("baseToken", {}).get("devAddress"),
    }

def is_blacklisted(token_data):
    """Check if the token or dev is blacklisted."""
    token_address = token_data.get("token_address")
    dev_address = token_data.get("dev_address")
    
    if token_address in BLACKLIST["coins"]:
        logs.append(f"Token {token_address} is blacklisted.")
        return True
    if dev_address in BLACKLIST["devs"]:
        logs.append(f"Dev {dev_address} is blacklisted.")
        return True
    return False

def apply_filters(token_data):
    """Apply filters to the token data."""
    liquidity = float(token_data.get("liquidity_usd", 0))
    price_change = calculate_price_change(token_data.get("token_address"))
    
    if liquidity < FILTERS["min_liquidity_usd"]:
        logs.append(f"Token {token_data['token_address']} has low liquidity.")
        return False
    if price_change > FILTERS["max_price_change_24h"]:
        logs.append(f"Token {token_data['token_address']} has high price volatility.")
        return False
    return True

def calculate_price_change(token_address):
    """Calculate the 24-hour price change for a token."""
    query = f"""
    SELECT price_usd FROM token_metrics
    WHERE token_address = '{token_address}'
    ORDER BY timestamp DESC
    LIMIT 2
    """
    df = pd.read_sql(query, engine)
    if len(df) >= 2:
        return (df.iloc[0]["price_usd"] - df.iloc[1]["price_usd"]) / df.iloc[1]["price_usd"]
    return 0

def detect_fake_volume(token_address):
    """Detect fake volume using Pocket Universe API."""
    headers = {"Authorization": f"Bearer {POCKET_UNIVERSE_API_KEY}"}
    payload = {"token_address": token_address}
    response = requests.post(POCKET_UNIVERSE_API_URL, headers=headers, json=payload)
    
    if response.status_code == 200:
        analysis = response.json()
        fake_volume_percentage = analysis.get("fake_volume_percentage", 0)
        logs.append(f"Fake volume percentage for {token_address}: {fake_volume_percentage}%")
        return fake_volume_percentage
    else:
        logs.append(f"Failed to analyze token {token_address} with Pocket Universe.")
        return 0

def check_rugcheck(token_address):
    """Check token on RugCheck.xyz."""
    url = f"{RUGCHECK_API_URL}/{token_address}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("status") == "Good", data.get("is_bundled", False)
    else:
        logs.append(f"Failed to check token {token_address} on RugCheck.")
        return False, False

def update_blacklist(token_address, dev_address):
    """Update blacklist with token and dev address."""
    BLACKLIST["coins"].append(token_address)
    BLACKLIST["devs"].append(dev_address)
    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)
    logs.append(f"Added {token_address} and dev {dev_address} to blacklist.")

def save_to_database(data):
    """Save parsed data to the database."""
    df = pd.DataFrame([data])
    df.to_sql("token_metrics", engine, if_exists="append", index=False)

def analyze_patterns():
    """Analyze historical data to identify patterns."""
    query = """
    SELECT * FROM token_metrics
    WHERE timestamp > NOW() - INTERVAL '1 day'
    """
    df = pd.read_sql(query, engine)
    
    # Example: Identify tokens with a sudden price drop (rug pull)
    df["price_change"] = df.groupby("token_address")["price_usd"].pct_change()
    rugged_tokens = df[df["price_change"] < -0.5]  # 50% price drop
    logs.append("Potential Rug Pulls: " + str(rugged_tokens))

def main():
    """Main function to run the bot."""
    token_addresses = ["0x...", "0x..."]  # Add token addresses to monitor
    while True:
        for token_address in token_addresses:
            token_data = fetch_token_data(token_address)
            parsed_data = parse_token_data(token_data)
            if parsed_data and not is_blacklisted(parsed_data) and apply_filters(parsed_data):
                fake_volume_percentage = detect_fake_volume(token_address)
                if fake_volume_percentage < FILTERS["max_fake_volume_percentage"]:
                    is_good, is_bundled = check_rugcheck(token_address)
                    if is_good and not is_bundled:
                        save_to_database(parsed_data)
                        send_telegram_message(f"✅ Token {parsed_data['token_name']} ({token_address}) is safe to trade.")
                        execute_bonkbot_trade("buy", token_address, "0.1")  # Example: Buy 0.1 ETH worth
                    elif is_bundled:
                        update_blacklist(token_address, parsed_data["dev_address"])
                        send_telegram_message(f"🚨 Token {parsed_data['token_name']} ({token_address}) has bundled supply and is blacklisted.")
                else:
                    logs.append(f"Token {token_address} has high fake volume and is excluded.")
        analyze_patterns()
        time.sleep(UPDATE_INTERVAL)