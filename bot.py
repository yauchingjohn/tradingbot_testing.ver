# bot.py - Pure Price Action: Market Structure + Demand Zones
import time
import logging
from datetime import datetime
from collections import deque
from api import get_ticker, get_balance, place_order
from config import API_KEY, SECRET_KEY
import json

# ---------- CONFIGURATION  ----------
PAIRS = [
    "BNB/USD", "BTC/USD", "EOS/USD", "ETC/USD",
    "ETH/USD", "BAT/USD", "LINK/USD", "SOL/USD", "ASTER/USD"
]
RISK_PERCENT = 25    #Risk per trade
RR_MIN = 2.5

# ---------- Logging ----------
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ---------- Global State ----------
price_history = {p: deque(maxlen=200) for p in PAIRS}   # keep last 200 mins
highs = {p: [] for p in PAIRS}          # list of swing highs
lows  = {p: [] for p in PAIRS}          # list of swing lows
demand_zones = {p: [] for p in PAIRS}   # list of (low, high) tuples
HELD_PAIR = None
POS_QTY = 0.0
END_DATE = datetime(2025, 11, 26, 23, 59)   # force exit

# ---------- Helpers ----------
def get_usd_free():
    bal = get_balance()
    return float(bal.get("USD", {}).get("Free", "0")) if bal else 0.0

def is_uptrend(pair):
    """True if last low broke previous high → valid uptrend"""
    if len(lows[pair]) < 2 or len(highs[pair]) < 2:
        return False
    last_low = lows[pair][-1]
    prev_high = highs[pair][-2] if len(highs[pair]) >= 2 else 0
    return last_low < prev_high  # low broke previous high

def detect_swing_points(pair):
    """Detect swing highs/lows (simplified)"""
    prices = list(price_history[pair])
    if len(prices) < 5:
        return
    mid = prices[-3]
    left, right = prices[-5:-3], prices[-2:]
    if all(mid > x for x in left) and all(mid > x for x in right):
        highs[pair].append(mid)
        if len(highs[pair]) > 10:
            highs[pair] = highs[pair][-10:]
    if all(mid < x for x in left) and all(mid < x for x in right):
        lows[pair].append(mid)
        if len(lows[pair]) > 10:
            lows[pair] = lows[pair][-10:]

def find_demand_zone(pair):
    """Find latest demand zone: consolidation → strong upward impulse"""
    global demand_zones
    prices = list(price_history[pair])
    if len(prices) < 20:
        return None
    for i in range(len(prices)-15, len(prices)-5):
        window = prices[i-10:i]
        if max(window) - min(window) < (max(prices[i:]) - prices[i]) * 0.3:
            impulse = prices[i+5] - prices[i] if i+5 < len(prices) else 0
            if impulse > 0:
                zone_low = min(window)
                zone_high = max(window)
                zone = (zone_low, zone_high)
                # Store latest zone
                if pair not in demand_zones:
                    demand_zones[pair] = []
                demand_zones[pair].append(zone)
                if len(demand_zones[pair]) > 5:
                    demand_zones[pair] = demand_zones[pair][-5:]
                return zone
    return None
def rr_valid(entry, sl, tp):
    """Risk-to-Reward ≥ 2.5:1"""
    risk = entry - sl
    reward = tp - entry
    return reward / risk >= RR_MIN if risk > 0 else False

# ---------- Core Decision ----------
def decision():
    global HELD_PAIR, POS_QTY

    try:
        logging.info("Decision loop started")
        now = datetime.now()
        if now >= END_DATE and HELD_PAIR:
            price = get_ticker(HELD_PAIR)["Data"][HELD_PAIR]["LastPrice"]
            resp = place_order(HELD_PAIR, "SELL", POS_QTY)
            logging.info(f"FINAL SELL {POS_QTY} {HELD_PAIR} @ {price:.2f} → {json.dumps(resp)}")
            if resp.get("Status") == "FILLED":
                HELD_PAIR, POS_QTY = None, 0.0
            return

        usd_free = get_usd_free()
        logging.info(f"USD free: {usd_free:.2f}")
        if usd_free < 10:
            logging.warning("Low USD balance - skipping")
            return

        # Update price & swings
        for pair in PAIRS:
            ticker = get_ticker(pair)
            if not ticker or pair not in ticker.get("Data", {}):
                logging.warning(f"Failed to fetch ticker for {pair}")
                continue
            price = float(ticker["Data"][pair]["LastPrice"])
            price_history[pair].append(price)
            logging.info(f"Price {pair}: {price:.2f}")
            detect_swing_points(pair)

        # SELL: if held and price breaks valid low
        if HELD_PAIR and HELD_PAIR in price_history:
            if lows[HELD_PAIR] and price_history[HELD_PAIR][-1] < lows[HELD_PAIR][-1]:
                price = price_history[HELD_PAIR][-1]
                resp = place_order(HELD_PAIR, "SELL", POS_QTY)
                logging.info(f"STRUCTURE BREAK SELL {POS_QTY} {HELD_PAIR} @ {price:.2f} → {json.dumps(resp)}")
                if resp.get("Status") == "FILLED":
                    HELD_PAIR, POS_QTY = None, 0.0
                return

        # BUY: only in uptrend + demand zone + R:R ≥ 2.5
        if not HELD_PAIR:
            candidates = []
            for pair in PAIRS:
                if not is_uptrend(pair):
                    continue
                zone = find_demand_zone(pair)
                if not zone:
                    continue
                zone_low, zone_high = zone
                price = price_history[pair][-1]
                if not (zone_low <= price <= zone_high):
                    continue

                sl = zone_low * 0.995
                tp = max(highs[pair][-3:]) if highs[pair] else price * 1.05
                if rr_valid(price, sl, tp):
                    candidates.append((pair, price, sl, tp, zone))

            if candidates:
                # Pick first valid (you can add scoring later)
                pair, entry, sl, tp, zone = candidates[0]
                risk_usd = usd_free * (RISK_PERCENT / 100)
                qty = round(risk_usd / entry, 6)
                resp = place_order(pair, "BUY", qty)
                logging.info(f"BUY {qty} {pair} @ {entry:.2f} | SL:{sl:.2f} TP:{tp:.2f} | ZONE:{zone} → {json.dumps(resp)}")
                if resp.get("Status") == "FILLED":
                    HELD_PAIR, POS_QTY = pair, qty
        logging.info("Decision loop ended")

    except Exception as e:
        logging.error(f"EXCEPTION: {e}")

# ---------- SYNCED LOOP: Run at :00 of every minute ----------

logging.info("=== PURE PRICE ACTION BOT STARTED (Uptrend + Demand + R:R 2.5) ===")
logging.info(f"Monitoring: {', '.join(PAIRS)} | 1-min candlestick sync")

# Run once immediately (for startup)
decision()

# Sync to the next :00
now = datetime.now()
seconds_to_next = 60 - now.second
if seconds_to_next < 60:
    logging.info(f"Syncing... next run in {seconds_to_next} seconds")
    time.sleep(seconds_to_next)

# Now run exactly at :00 every minute
while True:
    start_time = datetime.now()
    decision()
    elapsed = (datetime.now() - start_time).total_seconds()
    sleep_time = max(0, 60 - elapsed)  # Avoid drift
    time.sleep(sleep_time)
