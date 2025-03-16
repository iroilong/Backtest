# sma_strategy_bt.py

import backtrader as bt
from .sma_core import SmaCore


class SmaCoreStrategy(bt.Strategy):
    params = (("short_period", 5), ("long_period", 10))

    def __init__(self):
        # 初始化核心策略
        self.sma_core = SmaCore(self.p.short_period, self.p.long_period)
        self.order = None

    def next(self):
        # 取得目前價格（可根據需求調整，例如使用收盤價）
        current_price = self.data.close[0]
        # 將最新價格傳入核心策略
        signal = self.sma_core.update(current_price)

        # 若有待處理訂單則不再執行
        if self.order:
            return

        if not self.position:
            if signal == "buy":
                self.order = self.buy()
                self.log(f"Buy order executed at {current_price}")
        else:
            if signal == "sell":
                self.order = self.close()  # 或者sell()，依策略而定
                self.log(f"Sell order executed at {current_price}")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f"{dt}: {txt}")
