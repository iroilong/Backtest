# src/strategies/sma_strategy.py

import os
import pandas as pd
import backtrader as bt


# -----------------------------
# FractionalSizer：根據可用資金與當前價格計算下單數量（允許小數）
class FractionalSizer(bt.Sizer):
    params = (("percents", 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            size = (cash * self.p.percents / 100) / data.close[0]
            return size
        else:
            position = self.broker.getposition(data)
            return position.size


# -----------------------------
# SMA 策略：包含買賣訊號、統計下單次數與累計手續費
class SMAStrategy(bt.Strategy):
    params = (("short_period", 5), ("long_period", 20))

    def __init__(self):
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period
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

    def get_result(self):
        """
        回傳策略特有的結果
        """
        return {
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "total_commission": self.total_commission,
            "short_period": self.p.short_period,
            "long_period": self.p.long_period,
        }


# -----------------------------
# 單次 SMA 策略回測函數
def run_sma_backtest(
    engine, data, init_cash, percent, short_period, long_period, plot=True
):
    result = engine.run_strategy(
        strategy=SMAStrategy,
        data=data,
        initial_capital=init_cash,
        commission=0.0,
        short_period=short_period,
        long_period=long_period,
        plot=plot,
        sizer=FractionalSizer,
        sizer_params={"percents": percent},
    )
    return result


# -----------------------------
# 多組 SMA 策略回測函數
def run_sma_backtest_multi(
    engine, data, init_cashes, percents, short_periods, long_periods
):
    results = []
    for init_cash in init_cashes:
        for percent in percents:
            for short_period in short_periods:
                for long_period in long_periods:
                    if short_period >= long_period:
                        continue
                    result = run_sma_backtest(
                        engine,
                        data,
                        init_cash,
                        percent,
                        short_period,
                        long_period,
                        plot=False,
                    )
                    result["percent"] = percent
                    result["short_period"] = short_period
                    result["long_period"] = long_period
                    results.append(result)
    return pd.DataFrame(results)
