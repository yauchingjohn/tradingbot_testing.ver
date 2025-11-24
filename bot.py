# bot.py - Pure Price Action: Market Structure + Demand Zones
import time
import logging
from datetime import datetime, timedelta
from collections import deque
from api import get_ticker, get_balance, place_order
from config import API_KEY, SECRET_KEY
import json
import math
import requests
print("Bot started runnning!")

# ---------- CONFIGURATION  ----------
PAIRS = ["BNB/USD", "BTC/USD", "ETH/USD", "LINK/USD", "SOL/USD", "ASTER/USD", "1000CHEEMS/USD"]
RISK_PERCENT = 25    #Risk per trade
RR_MIN = 2.5

# ---------- Logging ----------
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ---------- Global State ----------
price_history = {p: deque(maxlen=2880) for p in PAIRS}   # keep last 2000 mins
highs = {p: [] for p in PAIRS}          # list of swing highs
lows  = {p: [] for p in PAIRS}          # list of swing lows
demand_zones = {p: [] for p in PAIRS}   # list of (low, high) tuples
uptrend_state = {p: False for p in PAIRS}
# ========== INSTANT PRICE HISTORY FOR ALL PAIRS (CoinGecko) ==========
def preload_price_history():
    logging.info("Preloading 1 day of 5m price history from CoinGecko...")
    
    # CoinGecko IDs mapping
    coingecko_ids = {
        "BNB/USD":  "binancecoin",
        "BTC/USD":  "bitcoin",
        "ETH/USD":  "ethereum",
        "LINK/USD": "chainlink",
        "SOL/USD":  "solana",
        "ASTER/USD": "aster-2",
        "1000CHEEMS/USD": "1000chems"
    }
    
    to_timestamp = int(time.time())
    from_timestamp = to_timestamp - (24 * 3600) 

    for pair, cg_id in coingecko_ids.items():
        if cg_id is None:
            logging.info(f"Skipping {pair} (no CoinGecko ID)")
            continue
            
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart/range"
            params = {
                'vs_currency': 'usd',
                'from': from_timestamp,
                'to': to_timestamp,
                'precision': 4
            }
            
            r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                logging.warning(f"CoinGecko HTTP {r.status_code} for {pair} → skipping")
                continue
                
            data = r.json()
            if 'prices' not in data or len(data['prices']) < 100:
                logging.warning(f"Too few prices from CoinGecko for {pair}")
                continue
                
            # CoinGecko returns [timestamp_ms, price] → take only prices
            prices = [price for timestamp_ms, price in data['prices']]
            
            # Take last 600 points (or less if not enough)
            closes = prices[-600:]
            
            # Fill deque
            price_history[pair].clear()
            price_history[pair].extend(closes)
            
            last_time = datetime.fromtimestamp(data['prices'][-1][0] / 1000)
            logging.info(f"{pair} → loaded {len(closes)} closes | latest: {closes[-1]:.6f} at {last_time.strftime('%H:%M')}")

# === PRE-COMPUTE SWINGS ===
            # Simulate adding prices one by one so detect_swing_points works
            highs[pair].clear()
            lows[pair].clear()
            for i in range(15, len(closes)):  # need at least 15 candles
                price_history[pair].popleft()
                price_history[pair].append(closes[i])
                detect_swing_points(pair)
                price_history[pair].popleft()
                price_history[pair].extend(closes[:i+1])  # restore full history
            
            # Restore full 600
            price_history[pair].clear()
            price_history[pair].extend(closes)
            
            # === PRE-COMPUTE DEMAND ZONES ===
            demand_zones[pair].clear()
            for i in range(38, len(closes)):  # need at least 15 candles
                price_history[pair].popleft()
                price_history[pair].append(closes[i])
                find_demand_zone(pair)
                price_history[pair].popleft()
                price_history[pair].extend(closes[:i+1])  # restore full history
            
            # Restore full 600
            price_history[pair].clear()
            price_history[pair].extend(closes)            
            '''for _ in range(5):  # try to find up to 5 zones
                zone = find_demand_zone(pair)
                if not zone:
                    break'''
                    
            logging.info(f"{pair} READY → History=600 | Swings H={len(highs[pair])} L={len(lows[pair])} | Zones={len(demand_zones[pair])}")
            
        except Exception as e:
            logging.error(f"Preload failed {pair}: {e}")            


# ======================================================================

HELD_POSITIONS = {pair: [] for pair in PAIRS}

END_DATE = datetime(2025, 11, 26, 23, 59)   # force exit

# ---------- Helpers ----------
def get_usd_free():
    bal = get_balance()
    if not bal or "SpotWallet" not in bal:
        logging.warning("get_balance() failed or no SpotWallet")
        return 0.0
    spot = bal["SpotWallet"]
    usd = spot.get("USD", {})
    free = usd.get("Free", "0")
    try:
        return float(free)
    except (ValueError, TypeError):
        logging.warning(f"Invalid USD Free value: {free}")
        return 0.0

def check_uptrend(pair):
    # Rule 1: Higher High + Higher Low → add to uptrend
    if len(lows[pair]) < 2 or len(highs[pair]) < 2:
        return False
    last_low = lows[pair][-1]
    prev_low = lows[pair][-2]
    last_high = highs[pair][-1]
    prev_high = highs[pair][-2]

    if last_high > prev_high and last_low > prev_low:
        uptrend_state[pair] = True
        logging.info(f"Uptrend detected on {pair} | LastHigh={last_high:.2f} > PrevHigh={prev_high:.2f}, LastLow={last_low:.2f} > PrevLow={prev_low:.2f}")
        return True
    # Rule 2: Lower High + Lower Low → remove from uptrend
    elif uptrend_state[pair] and last_high < prev_high and last_low < prev_low:
        uptrend_state[pair] = False
        logging.info(f"UPTREND BROKEN {pair}: LH + LL")
        return False

    # Otherwise → keep current state
    logging.info(f"UPTREND STATE STORED")
    return uptrend_state[pair]

def detect_swing_points(pair):
    """Detect swing highs/lows (simplified)"""
    prices = list(price_history[pair])
    if len(prices) < 15:
        return
    mid = prices[-8]
    left, right = prices[-15:-8], prices[-7:]
    if all(mid > x for x in left) and all(mid > x for x in right):
        highs[pair].append(mid)
    if all(mid < x for x in left) and all(mid < x for x in right):
        lows[pair].append(mid)

def find_demand_zone(pair):
    """Find latest demand zone: consolidation → strong upward impulse"""
    global demand_zones
    prices = list(price_history[pair])
    if len(prices) < 38:
        return None
    for i in range(len(prices)-23, len(prices)-8):
        window = prices[i-15:i]
        if max(window) - min(window) < (max(prices[i:]) - prices[i]) * 0.3:
            impulse = prices[i+8] - prices[i] if i+8 < len(prices) else 0
            if impulse > 0:
                zone_low = min(window)
                zone_high = max(window)
                zone = (zone_low, zone_high)
                logging.info(f"Demand zone founded{pair}: {zone} | Impulse={impulse:.2f}")
                # Store latest zone
                if pair not in demand_zones:
                    demand_zones[pair] = []
                # Only append if it's not the same as the last zone
                if not demand_zones[pair] or demand_zones[pair][-1] != zone:
                    demand_zones[pair].append(zone)

                if len(demand_zones[pair]) > 5:
                    demand_zones[pair] = demand_zones[pair][-5:]
                logging.info(f"Demand zones for {pair}: {json.dumps(demand_zones.get(pair))}")
                return zone
    return None
def rr_valid(entry, sl, tp):
    """Risk-to-Reward ≥ 2.5:1"""
    risk = entry - sl
    reward = tp - entry
    return reward / risk >= RR_MIN if risk > 0 else False

# ---------- Core Decision ----------
def decision():
    global HELD_POSITIONS, sl, tp, uptrend_state

    try:
        logging.info("Decision loop started")
        now = datetime.now()
        if now >= END_DATE and HELD_POSITIONS:
            for pair, pos in list(HELD_POSITIONS.items()):
                price = get_ticker(pair)["Data"][pair]["LastPrice"]
                resp = place_order(pair, "SELL", pos["qty"])
                logging.info(f"FINAL SELL {pos['qty']} {pair} @ {price:.2f} → {json.dumps(resp)}")
                if resp.get("Status") == "FILLED":
                    del HELD_POSITIONS[pair]   # remove position after final sell
            return
        for pair in PAIRS:
            h = len(highs[pair])
            l = len(lows[pair])
            p = len(price_history[pair])
            logging.info(f"DEBUG {pair}: History={p}, Highs={h}, Lows={l}")

        usd_free = get_usd_free()
        logging.info(f"USD free: {usd_free:.2f}")
        if usd_free < 10:
            logging.warning("Low USD balance - skipping")
            return

        # Update price & swings
        for pair in PAIRS:
            try:
                ticker = get_ticker(pair)
                if not ticker:
                    logging.warning(f"get_ticker({pair}) returned None")
                    continue
                data = ticker.get("Data", {})
                if pair not in data:
                    logging.warning(f"Pair {pair} not in Data: {list(data.keys())}")
                    continue
                price = float(data[pair]["LastPrice"])
                price_history[pair].append(price)
                logging.info(f"Price {pair}: {price:.2f}")
                detect_swing_points(pair)
            except Exception as e:
                logging.error(f"ERROR on {pair}: {e}")
                continue

        # SELL: loop through all held positions
        # Inside your main loop — replace the old SL/TP block
        for pair in list(HELD_POSITIONS.keys()):
            current_price = price_history[pair][-1]
            positions_to_remove = []
    
            for i, pos in enumerate(HELD_POSITIONS[pair]):
                if current_price <= pos["sl"]:
                    logging.info(f"SL HIT {pair} → SELL {pos['qty']} @ {current_price:.4f}")
                    place_order(pair, "SELL", pos["qty"])
                    positions_to_remove.append(i)
            
                elif current_price >= pos["tp"]:
                    logging.info(f"TP HIT {pair} → SELL {pos['qty']} @ {current_price:.4f}")
                    place_order(pair, "SELL", pos["qty"])
                    positions_to_remove.append(i)
    
    # Remove hit positions (from last to first to avoid index shift)
            for i in sorted(positions_to_remove, reverse=True):
                del HELD_POSITIONS[pair][i]
    
            if not HELD_POSITIONS[pair]:
                del HELD_POSITIONS[pair]  # clean up empty list

        # BUY: only in uptrend + demand zone + R:R ≥ 2.5

        candidates = []
        for pair in PAIRS:
            price = price_history[pair][-1]
            find_demand_zone(pair)            
            if not check_uptrend(pair):
                continue
            # Skip if no zones stored
            if pair not in demand_zones or not demand_zones[pair]:
                continue
            matched_zone = None
            for zone_low, zone_high in demand_zones[pair]:
            # Check if current price is inside the zone
                if zone_low <= price <= zone_high:
                # Check last 3 prices > zone_high
                    if len(price_history[pair]) >= 3:
                        last3 = list(price_history[pair])[-4:-1]
                        if all(p > zone_high for p in last3):
                            matched_zone = (zone_low, zone_high)
                            logging.info(f"matched demand zone for {pair} at price {price:.2f} in zone {matched_zone}")
                            break   # stop at first valid zone

            if not matched_zone:
                logging.info(f"No valid demand zone found for {pair} at price {price:.2f}")
                continue  # skip if no valid zone found
            prices = list(price_history[pair])[-15:]  # last 15 closes
            diffs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
            sl = zone_low - max(diffs)
            
            # Updated TP without empty max error
            recent_highs = highs[pair][-8:]
            if recent_highs:
                tp = max(recent_highs)
            else:
                tp = price * 1.05
                logging.info(f"No recent highs for {pair}, using 5% TP")
            if rr_valid(price, sl, tp):
                candidates.append((pair, price, sl, tp, matched_zone))
            else:
                logging.info(f"{pair} skipped: RR invalid (entry={price}, SL={sl}, TP={tp})")
        if candidates:
            # Pick first valid (you can add scoring later)
            pair, entry, sl, tp, matched_zone = candidates[0]
            risk_usd = usd_free * (RISK_PERCENT / 100)
            qty = math.floor((risk_usd / entry) * 10) / 10
            resp = place_order(pair, "BUY", qty)
            logging.info(f"BUY {qty} {pair} @ {entry:.2f} | SL:{sl:.2f} TP:{tp:.2f} | ZONE:{matched_zone} → {json.dumps(resp)}")
            status = str(resp.get("OrderDetail", {}).get("Status", "")).strip().upper()
            filled_qty = float(resp.get("OrderDetail", {}).get("FilledQuantity", 0) or 0)
            logging.info(f"BUY ack status={status}, filled_qty={filled_qty}, resp={json.dumps(resp)}")
            if status == "FILLED" or filled_qty > 0:
                logging.info("BUY ORDER FILLED")
                HELD_POSITIONS[pair].append({"qty": qty, "entry": entry, "sl": sl, "tp": tp})
                logging.info("HELD POSITIONS UPDATED")
            else:
                logging.info(f"BUY not marked FILLED yet: status={status}")
        
            # Add this anywhere to see all open trades
            for pair, positions in HELD_POSITIONS.items():
                for i, pos in enumerate(positions):
                    logging.info(f"POS {i+1} {pair}: qty={pos['qty']} entry={pos['entry']:.4f} SL={pos['sl']:.4f} TP={pos['tp']:.4f}")

        logging.info("Decision loop ended")

    except Exception as e:
        logging.error(f"EXCEPTION: {e}")

# ---------- SYNCED LOOP: Run at :00 of every minute ----------

logging.info("=== PURE PRICE ACTION BOT STARTED (Uptrend + Demand + R:R 2.5) ===")
logging.info(f"Monitoring: {', '.join(PAIRS)} | 1-min candlestick sync")
# RUN THIS ONCE AT STARTUP
preload_price_history()
#Run once immediately (for startup)
while True:
    decision()
    now = datetime.now()
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    sleep_time = (next_minute - now).total_seconds()
    if sleep_time > 0:
        logging.info(f"Syncing... next run in {sleep_time} seconds")
        time.sleep(sleep_time)
