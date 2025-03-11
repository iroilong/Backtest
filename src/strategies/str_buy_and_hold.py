import os
import sqlite3
import pandas as pd
import datetime
import backtrader as bt


def load_data(db_path: str):
    """
    從 SQLite 資料庫讀取 kline 資料表，依據 datetime 排序，
    將 datetime 欄位轉換成 pandas datetime 物件，
    並設定成 DataFrame 的 index，符合 backtrader 所需格式。
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"資料庫不存在：{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM kline ORDER BY datetime ASC", conn)
    finally:
        conn.close()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    if "openinterest" not in df.columns:
        df["openinterest"] = 0
    return df


class BuyAndHold(bt.Strategy):
    """
    最簡單的買進持有策略：
    在第一根 K 線買進，持有到回測結束。
    """

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.order_executed = False

    def next(self):
        if not self.position and not self.order_executed:
            self.buy()  # 第一根 K 線買進
            self.order_executed = True
            print(
                f"買入訂單在 {self.datas[0].datetime.date(0)} 執行，買價: {self.dataclose[0]:.2f}"
            )


if __name__ == "__main__":
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100.0)

    # 指定資料庫路徑
    db_path = os.path.join("data", "binance_BTC_USDT_1d.sqlite")
    df = load_data(db_path)

    # 指定回測開始與結束時間 (以 UTC 或資料中的時間格式為主)
    backtest_start = pd.to_datetime("2023-07-01")
    backtest_end = pd.to_datetime("2024-03-10 23:59:59")

    # 篩選出指定回測期間的資料
    df = df.loc[backtest_start:backtest_end]
    if df.empty:
        raise ValueError("指定的回測區間內無資料")

    # 建立 backtrader 的資料來源
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # 加入策略
    cerebro.addstrategy(BuyAndHold)

    print("Starting Portfolio Value: %.2f" % cerebro.broker.getvalue())
    cerebro.run()
    print("Final Portfolio Value: %.2f" % cerebro.broker.getvalue())

    cerebro.plot()
