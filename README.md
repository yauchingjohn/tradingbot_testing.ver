# tradingbot_testing.ver
testing version of crypto trading bot
# Roostoo Trading Bot – SMA Crossover

**Strategy**: 5/15 SMA crossover on BTC/USD  
**Risk**: 2% per trade  
**Polling**: Every 5 minutes  

## Run on AWS

```bash
git clone https://github.com/yourusername/roostoo-trading-bot.git
cd roostoo-trading-bot
pip install -r requirements.txt
export API_KEY="your_key"
export SECRET_KEY="your_secret"
nohup python3 bot.py &
