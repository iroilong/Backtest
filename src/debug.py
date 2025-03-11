import ccxt

exchange = ccxt.binance()  # 你可以換成其他交易所，如 ccxt.okx()、ccxt.bybit()
exchange.load_markets()

# 查看 Binance 支援的 timeframe
print(exchange.timeframes.keys())
