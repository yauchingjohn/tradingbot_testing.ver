# bot.py
import time
import logging
from datetime import datetime
import schedule
from api import get_price, get_balance, place_market_order
from config import PAIR, POLL_MINUTES, RISK_PERCENT

logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

price_history = []
POSITION = 0.0

def calculate_sma(series, period):
    return sum(series[-period:]) / period if len(series) >= period else None
def decision():
    global POSITION, price_history
    try:
        # Use new get_ticker
        ticker_data = get_ticker(PAIR)
        if not ticker_data or "Data" not in ticker_data:
            logging.error("Failed to get ticker")
            return
        price = float(ticker_data["Data"][PAIR]["LastPrice"])
        price_history.append(price)
        if len(price_history) > 30:
            price_history = price_history[-30:]

        logging.info(f"Price {PAIR}: {price}")

        if len(price_history) < 15:
            logging.info("Waiting for more data...")
            return

        sma5 = calculate_sma(price_history, 5)
        sma15 = calculate_sma(price_history, 15)
        logging.info(f"SMA5={sma5:.2f}  SMA15={sma15:.2f}")

        # Use new get_balance
        balance = get_balance()
        if not balance:
            logging.error("Failed to get balance")
            return
        usd_free = float(balance.get("USD", {}).get("Free", "0"))
        btc_free = float(balance.get("BTC", {}).get("Free", "0"))

        if sma5 > sma15 and POSITION == 0 and usd_free > 10:
            risk_usd = usd_free * (RISK_PERCENT / 100)
            qty = round(risk_usd / price, 6)
            resp = place_order(PAIR, "BUY", qty)  # MARKET by default
            logging.info(f"BUY {qty} BTC → {resp}")
            if resp and resp.get("Status") == "FILLED":
                POSITION = qty

        elif sma5 < sma15 and POSITION > 0:
            resp = place_order(PAIR, "SELL", POSITION)
            logging.info(f"SELL {POSITION} BTC → {resp}")
            if resp and resp.get("Status") == "FILLED":
                POSITION = 0.0

    except Exception as e:
        logging.error(f"ERROR in decision: {e}")
        
schedule.every(POLL_MINUTES).minutes.do(decision)

logging.info("BOT STARTED")
decision()
while True:
    schedule.run_pending()
    time.sleep(1)
