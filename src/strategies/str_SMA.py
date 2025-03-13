import os
import sqlite3
import pandas as pd
import datetime
import backtrader as bt


# ---------------------------------------------
# 自訂 FractionalSizer：根據可用資金與當前價格計算下單數量（允許小數）
class FractionalSizer(bt.Sizer):
    params = (("percents", 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            size = (cash * self.p.percents / 100) / data.close[0]
            return size
        else:
            position = self.broker.getposition(data)
            return position.size


# ---------------------------------------------
# Commission 設定：手續費計算在 notify_order 中處理，所以這裡直接回傳 0
class MakerTakerCommission(bt.CommInfoBase):
    def getcommission(self, size, price):
        return 0


# ---------------------------------------------
# 資料載入函數
def load_data(db_path: str):
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


# ---------------------------------------------
# 定義 SMA 交叉策略，並統計下單次數與累計手續費
class SmaCrossoverStrategy(bt.Strategy):
    params = (("short_period", 5), ("long_period", 20))

    def __init__(self):
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.long_period
        )
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
        self.order = None
        self.buy_count = 0
        self.sell_count = 0
        self.total_commission = 0.0

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                # 使用市價單買入以確保成交 (視為 taker)
                order = self.buy(exectype=bt.Order.Market)
                order.info["maker_or_taker"] = "taker"
                self.order = order
                print(
                    f"Buy Order Submitted at {self.datas[0].datetime.date(0)}, Price: {self.datas[0].close[0]:.2f}"
                )
        else:
            if self.crossover < 0:
                order = self.close(exectype=bt.Order.Market)
                order.info["maker_or_taker"] = "taker"
                self.order = order
                print(
                    f"Sell Order Submitted at {self.datas[0].datetime.date(0)}, Price: {self.datas[0].close[0]:.2f}"
                )

    def notify_order(self, order):
        if order.status == order.Completed:
            trade_value = abs(order.executed.size * order.executed.price)
            # 預設 taker 費率 0.04%，maker 費率 0.02%
            commrate = 0.0004
            if order.info.get("maker_or_taker", "taker") == "maker":
                commrate = 0.0002
            commission = trade_value * commrate
            order.executed.comm = commission
            self.total_commission += commission

            if order.isbuy():
                self.buy_count += 1
                print(
                    f"BUY EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.5f}, Comm: {commission:.2f}"
                )
            else:
                self.sell_count += 1
                print(
                    f"SELL EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.5f}, Comm: {commission:.2f}"
                )
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            print("Order Canceled/Margin/Rejected")
        self.order = None


# ---------------------------------------------
# 單組參數回測函數，增加參數 plot（預設 True）決定是否繪圖
def run_backtest(
    init_cash,
    percent,
    short_period,
    long_period,
    backtest_start,
    backtest_end,
    db_path,
    plot=True,
):
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(init_cash)
    cerebro.addsizer(FractionalSizer, percents=percent)
    comminfo = MakerTakerCommission()
    cerebro.broker.addcommissioninfo(comminfo)

    # 載入資料並過濾回測區間
    df = load_data(db_path)
    df = df.loc[backtest_start:backtest_end]
    if df.empty:
        raise ValueError("指定回測區間內無資料")

    data = bt.feeds.PandasData(dataname=df.copy())
    cerebro.adddata(data)

    cerebro.addstrategy(
        SmaCrossoverStrategy, short_period=short_period, long_period=long_period
    )

    print(
        f"Running backtest: init_cash={init_cash}, percent={percent}, short_period={short_period}, long_period={long_period}"
    )
    strategies = cerebro.run()
    strat = strategies[0]
    final_cash = cerebro.broker.getvalue()
    profit = final_cash - init_cash
    profit_rate = profit / init_cash * 100.0
    print(
        f"Final Cash: {final_cash:.2f}, Profit: {profit:.2f}, Net Profit Rate: {profit_rate:.2f}%"
    )

    if plot:
        cerebro.plot()

    return {
        "backtest_start": backtest_start.strftime("%Y-%m-%d"),
        "backtest_end": backtest_end.strftime("%Y-%m-%d"),
        "initial_cash": init_cash,
        "percents": percent,
        "short_period": short_period,
        "long_period": long_period,
        "buy_count": strat.buy_count,
        "sell_count": strat.sell_count,
        "total_commission": strat.total_commission,
        "final_cash": final_cash,
        "profit": profit,
        "net_profit_rate": profit_rate,
    }


# ---------------------------------------------
# 多組參數回測函數：遍歷多組參數，重複呼叫 run_backtest()，整理結果成 DataFrame
def run_backtest_multi(
    init_cashes,
    percents,
    short_periods,
    long_periods,
    backtest_start,
    backtest_end,
    db_path,
):
    results = []
    for init_cash in init_cashes:
        for percent in percents:
            for short_period in short_periods:
                for long_period in long_periods:
                    if short_period >= long_period:
                        continue  # 僅測試短均線 < 長均線的組合
                    print("=" * 50)
                    result = run_backtest(
                        init_cash,
                        percent,
                        short_period,
                        long_period,
                        backtest_start,
                        backtest_end,
                        db_path,
                        plot=False,
                    )
                    results.append(result)
    return pd.DataFrame(results)


# ---------------------------------------------
if __name__ == "__main__":
    # 測試參數設定
    backtest_start = pd.to_datetime("2024-01-01")
    backtest_end = pd.to_datetime("2025-03-10 23:59:59")
    db_path = os.path.join("data", "binance_BTC_USDT_1h.sqlite")

    # 可測試的參數列表
    init_cashes = [10000]
    percents = [10, 50]
    short_periods = [
        5,
        10,
        20,
    ]
    long_periods = [
        20,
        60,
        120,
    ]

    RUN_SINGLE = 1
    if RUN_SINGLE:
        # 若只想執行單次回測，可以呼叫 run_backtest() 並設定 plot=True
        result = run_backtest(
            10000, 50, 5, 20, backtest_start, backtest_end, db_path, plot=True
        )
        print(result)
    else:
        # 執行多組參數回測 (不繪圖)
        results_df = run_backtest_multi(
            init_cashes,
            percents,
            short_periods,
            long_periods,
            backtest_start,
            backtest_end,
            db_path,
        )
        results_df_sorted = results_df.sort_values(by="net_profit_rate")
        print("\n多組回測結果:")
        print(results_df_sorted)
        results_df_sorted.to_csv("backtest_report.csv", index=False)
