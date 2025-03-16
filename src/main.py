from utils.data_loader import DataLoader
import backtrader as bt
import pandas as pd
from strategies.sma_strategy_bt import SmaCoreStrategy

import os
import time

# 測試範例：僅需傳入交易所參數 exchange_config
exchange_config = {
    "exchange_id": "binance",
    "symbol": "BTC/USDT",
    "timeframe": "1m",
}
tablename = DataLoader.generate_table_name(exchange_config)
print(f"使用的資料表名稱: {tablename}")

data_loader = DataLoader()

df = data_loader.load_data(
    exchange_config=exchange_config,
    destination="ccxt",
    start_time="2025-03-03 00:00:00",
    end_time="2025-03-08 15:59:59",
)
print(df.head())


# 載入資料後，先轉換 datetime 欄位
if "datetime" in df.columns:
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        sample = df["datetime"].iloc[0]
        if isinstance(sample, (int, float)):
            df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
        else:
            df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
else:
    raise KeyError("資料中必須包含 'datetime' 欄位")


datafeed = bt.feeds.PandasData(dataname=df)

cerebro = bt.Cerebro()
cerebro.adddata(datafeed)
cerebro.addstrategy(SmaCoreStrategy, short_period=5, long_period=20)
cerebro.broker.setcash(10000)
cerebro.run()
cerebro.plot()
