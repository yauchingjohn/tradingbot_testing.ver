## Description
1. Trading Bot running on Roostoo for a 2-week competition.
2. The strategy is built mainly based on observing **market structure** and **buying pressure** in different price level.

## Data Sources
1. Bot data feeding from coingecko's historical data
2. Real-time market data from Roostoo (getting the closing price of every 1-min candlestick)

## Strategy Overview
1. Detect **swing highs/lows**
2. Wait for uptrend confirmation (Higher Highs + Higher Lows)
3. Finding **demand zones** with strong buying pressure

## Entry Rules
1. Only enter long positions
2. Only enter trades when the following three **buying signals** are satisfied **simultaneously**:
   1. Uptrend is confirmed and not broken
   2. Price retest on the demand zone
   3. Risk-Return Ratio must be greater than 2.5:1 (i.e. (TP - Entry price) / (Entry price - SL) >= 2.5
## Exit Rules
1. Stop loss (SL) = Lowest point of demand zone - 14-day max price diff (similar concept with 14-day ATR)
2. Target Profit (TP) = Max Recent Highs
   
## Risk Management
1. Size of each position: 25% of **remaining** capital
2. Buy spot only
