import os
import pandas as pd
import backtrader as bt
import time


# -----------------------------
# 固定金額 Sizer：每次下單金額固定為初始資金的固定百分比
class FixedAmountSizer(bt.Sizer):
    params = (("fixed_percent", 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        initial_cash = self.broker.startingcash
        order_value = initial_cash * self.p.fixed_percent / 100.0
        if cash < order_value:
            order_value = cash
        size = order_value / data.close[0]
        return size


# -----------------------------
# Commission 設定：手續費計算（這裡直接回傳 0，實際計算在 notify_order 中處理）
class MakerTakerCommission(bt.CommInfoBase):
    def getcommission(self, size, price):
        return 0


# -----------------------------
# 策略：連續 N 根陰線後等待第一根陽線進場，下市價單買入
# 之後根據買入價格設定止盈與止損，並在出場時全數平倉
class ConsecutiveBearishBuyMarketStrategy(bt.Strategy):
    params = (
        ("consecutive", 3),  # 連續陰線門檻
        ("take_profit_pct", 3),  # 止盈百分比（例如 +3%）
        ("stop_loss_pct", -2),  # 止損百分比（例如 -2%）
    )

    def __init__(self):
        self.streak_count = 0  # 累計連續陰線數
        self.triggered = False  # 觸發旗標：達到連續陰線門檻後開始等待第一根陽線
        self.order = None
        self.buy_count = 0
        self.sell_count = 0
        self.total_commission = 0.0
        self.event_log = []  # 紀錄交易事件
        self.in_trade = False  # 旗標：是否持有部位

    def next(self):
        # 若已有持倉，檢查止盈與止損條件
        if self.in_trade and self.position:
            entry_price = self.position.price
            target_profit = entry_price * (1 + self.p.take_profit_pct / 100.0)
            target_stop = entry_price * (1 + self.p.stop_loss_pct / 100.0)
            if self.data.high[0] >= target_profit:
                self.log(
                    f"止盈觸發：當前High {self.data.high[0]:.2f} >= 止盈目標 {target_profit:.2f}"
                )
                self.close(exectype=bt.Order.Market, info={"exit_reason": "止盈"})
                return
            elif self.data.low[0] <= target_stop:
                self.log(
                    f"止損觸發：當前Low {self.data.low[0]:.2f} <= 止損目標 {target_stop:.2f}"
                )
                self.close(exectype=bt.Order.Market, info={"exit_reason": "止損"})
                return
            return

        # 若無持倉，檢查進場條件
        if not self.in_trade:
            # 若尚未觸發，累計連續陰線
            if not self.triggered:
                if self.data.close[0] < self.data.open[0]:
                    self.streak_count += 1
                    if self.streak_count == self.p.consecutive:
                        self.triggered = True
                        self.log(
                            f"觸發條件達成：連續陰線數 = {self.streak_count}，開始等待第一根陽線進場"
                        )
                else:
                    # 陽線出現但尚未達到門檻則重置計數
                    self.streak_count = 0
            else:
                # 觸發後等待第一根陽線
                if self.data.close[0] > self.data.open[0]:
                    self.log(
                        f"第一根陽線出現，進場買入，成交價 {self.data.close[0]:.2f}"
                    )
                    self.buy(exectype=bt.Order.Market, info={"entry_log": True})
                    self.in_trade = True
                    self.triggered = False
                    self.streak_count = 0
                # 如果持續陰線，維持觸發狀態（不更新 streak_count 以保留觸發後的記錄）

    def notify_order(self, order):
        if order.status == order.Completed:
            trade_value = abs(order.executed.size * order.executed.price)
            # 使用新的手續費：maker 0.080%，taker 0.100%
            if order.info.get("maker_or_taker", "taker") == "maker":
                commrate = 0.0008
            else:
                commrate = 0.0010
            commission = trade_value * commrate
            order.executed.comm = commission
            self.total_commission += commission

            timestamp = self.data.datetime.datetime(0).strftime("%Y-%m-%d %H:%M:%S")
            if order.isbuy():
                self.buy_count += 1
                entry_price = order.executed.price
                target_profit = entry_price * (1 + self.p.take_profit_pct / 100.0)
                target_stop = entry_price * (1 + self.p.stop_loss_pct / 100.0)
                self.event_log.append(
                    {
                        "time": timestamp,
                        "event": "買入成交",
                        "price": entry_price,
                        "size": order.executed.size,
                        "commission": commission,
                        "target_profit": target_profit,
                        "target_stop": target_stop,
                    }
                )
                self.log(
                    f"BUY EXECUTED, Price: {entry_price:.2f}, Size: {order.executed.size:.5f}, Comm: {commission:.2f}, 止盈: {target_profit:.2f}, 止損: {target_stop:.2f}"
                )
            elif order.issell():
                self.sell_count += 1
                exit_reason = order.info.get("exit_reason", "未知")
                self.event_log.append(
                    {
                        "time": timestamp,
                        "event": f"賣出成交 ({exit_reason})",
                        "price": order.executed.price,
                        "size": order.executed.size,
                        "commission": commission,
                    }
                )
                self.log(
                    f"SELL EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.5f}, Comm: {commission:.2f} ({exit_reason})"
                )
                self.in_trade = False
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("訂單取消/保證金不足/拒絕")
            self.in_trade = False
        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {txt}")

    def get_result(self):
        """
        回傳策略特有的結果：
          - consecutive: 使用的連續陰線門檻
          - tp_pct: 止盈百分比（參數值）
          - sl_pct: 止損百分比（參數值）
        以及共通資訊：買入次數、賣出次數、總佣金
        """
        return {
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "total_commission": self.total_commission,
            "consecutive": self.p.consecutive,
            "tp_pct": self.p.take_profit_pct,
            "sl_pct": self.p.stop_loss_pct,
        }


# -----------------------------
# 單次回測函數
def run_bearish_reversal_backtest(
    engine, data, init_cash, percent, consecutive, tp_pct, sl_pct, plot=True
):
    result = engine.run_strategy(
        strategy=ConsecutiveBearishBuyMarketStrategy,
        data=data,
        initial_capital=init_cash,
        commission=0.0,
        consecutive=consecutive,
        take_profit_pct=tp_pct,
        stop_loss_pct=sl_pct,
        plot=plot,
        sizer=FixedAmountSizer,
        sizer_params={"fixed_percent": percent},
    )
    return result


# -----------------------------
# 多組回測函數
def run_bearish_reversal_backtest_multi(
    engine, data, init_cashes, percents, consecutives, tp_pct_list, sl_pct_list
):
    results = []
    total_start = time.time()  # 紀錄總開始時間
    for init_cash in init_cashes:
        for percent in percents:
            for consecutive in consecutives:
                for tp_pct in tp_pct_list:
                    for sl_pct in sl_pct_list:
                        if tp_pct <= 0 or sl_pct >= 0:
                            continue
                        print("=" * 50)
                        result = run_bearish_reversal_backtest(
                            engine,
                            data,
                            init_cash,
                            percent,
                            consecutive,
                            tp_pct,
                            sl_pct,
                            plot=False,
                        )
                        result.update(
                            {
                                # "init_cash": init_cash,
                                # "percent": percent,
                                "consecutive": consecutive,
                                "tp_pct": tp_pct,
                                "sl_pct": sl_pct,
                            }
                        )
                        results.append(result)
    total_elapsed = time.time() - total_start  # 計算總耗時
    print(f"多組回測總耗時: {total_elapsed:.2f} 秒")
    return pd.DataFrame(results)
