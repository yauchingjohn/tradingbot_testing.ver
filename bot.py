# bot.py - Roostoo AI Trading Bot (SMA Crossover)
# Team: [Your Team Name] | HKU Web3 Hackathon

import requests
import time
import hmac
import hashlib
import urllib.parse
from collections import deque
import logging
import os

# ========================= CONFIG =========================
API_KEY = os.getenv('API_KEY', 'YOUR_ROOSTOO_API_KEY_HERE')
SECRET_KEY = os.getenv('SECRET_KEY', 'YOUR_ROOSTOO_SECRET_KEY_HERE')
BASE_URL = 'https://mock-api.roostoo.com/v3'
PAIR = 'BTC/USD'
SHORT_WINDOW = 5
LONG_WINDOW = 15
QUANTITY = '0.001'  # BTC per trade (adjust)
RISK_PERCENT = 0.02  # 2% risk per trade
POLL_INTERVAL = 300  # 5 minutes

# Data
price_history = deque(maxlen=LONG_WINDOW * 2)
# =========================================================

logging.basicConfig(
    filename='trading_bot.log',
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

def get_timestamp():
    return str(int(time.time() * 1000))

def sign_payload(payload):
    param_str = '&'.join([f"{k}={urllib.parse.quote(str(v), safe='')}" 
                          for k, v in sorted(payload.items())])
    return hmac.new(SECRET_KEY.encode(), param_str.encode(), hashlib.sha256).hexdigest()

def api_request(endpoint, method='GET', params=None):
    if params is None:
        params = {}
    params['timestamp'] = get_timestamp()
    
    if method == 'POST':
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'RST-API-KEY': API_KEY,
            'MSG-SIGNATURE': sign_payload(params)
        }
        body = urllib.parse.urlencode(params)
        url = BASE_URL + endpoint
        response = requests.post(url, headers=headers, data=body)
    else:
        query = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        headers = {
            'RST-API-KEY': API_KEY,
            'MSG-SIGNATURE': sign_payload(params)
        }
        url = f"{BASE_URL}{endpoint}?{query}"
        response = requests.get(url, headers=headers)
    
    logging.info(f"API {method} {endpoint} → {response.status_code}")
    return response.json() if response.ok else None

def get_price():
    data = api_request('/ticker', params={'pair': PAIR})
    if data and data.get('Success'):
        return float(data['Data'][PAIR]['LastPrice'])
    return None

def get_balance():
    return api_request('/balance')

def place_order(side, quantity=QUANTITY):
    params = {
        'pair': PAIR,
        'side': side.upper(),
        'type': 'MARKET',
        'quantity': quantity
    }
    return api_request('/place_order', method='POST', params=params)

def has_position():
    balance = get_balance()
    if balance and balance.get('Success'):
        coin = PAIR.split('/')[0]
        return float(balance['Wallet'].get(coin, {}).get('Free', 0)) > 0
    return False

def sma(prices, window):
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window

# ========================= MAIN LOOP =========================
def main():
    logging.info("BOT STARTED")
    print("Bot started. Check trading_bot.log")

    while True:
        try:
            price = get_price()
            if price:
                price_history.append(price)
                logging.info(f"Price: {price}")

            if len(price_history) >= LONG_WINDOW:
                short = sma(price_history, SHORT_WINDOW)
                long = sma(price_history, LONG_WINDOW)

                if short and long:
                    in_position = has_position()

                    if short > long and not in_position:
                        bal = get_balance()
                        if bal:
                            usd = float(bal['Wallet']['USD']['Free'])
                            risk_qty = usd * RISK_PERCENT / price
                            qty = min(float(QUANTITY), risk_qty)
                            if qty > 0:
                                result = place_order('BUY', str(qty))
                                logging.info(f"BUY {qty} BTC → {result}")

                    elif short < long and in_position:
                        result = place_order('SELL')
                        logging.info(f"SELL → {result}")

            time.sleep(POLL_INTERVAL)

        except Exception as e:
            logging.error(f"ERROR: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
