"""
程式概要說明:
    此模組定義了基於 Backtrader 平台的 SMA 策略適配器 (SmaCoreStrategy)。
    策略使用核心 SMA 模組 (SmaCore) 計算買賣訊號，
    並在每根 K 線到來時根據訊號、空倉/持倉狀態與資金情況決定以市價單買入或平倉，
    同時計算買賣手續費並累計統計數據。圖表上亦加入短期與長期 SMA 線供參考。
"""

import backtrader as bt
from strategies.sma_core import SmaCore  # 引入核心 SMA 計算邏輯
import pandas as pd


class SmaCoreStrategy(bt.Strategy):
    params = (
        ("short_period", 5),  # 短期 SMA 週期設定
        ("long_period", 20),  # 長期 SMA 週期設定
        ("buy_pct", 0.3),  # 每次買入使用的初始資金比例 (例如 0.3 表示 30%)
        ("taker_fee_rate", 0.001),  # 買入時手續費率 (吃單，0.1%)
        ("maker_fee_rate", 0.0008),  # 賣出時手續費率 (掛單，0.08%)
    )

    def __init__(self):
        # 如果傳入的資料是 pandas DataFrame，檢查其索引是否為 datetime 類型
        # 若不是則進行轉換，確保資料 Feed 正常運作
        if hasattr(self.data, "_dataname") and isinstance(
            self.data._dataname, pd.DataFrame
        ):
            if not pd.api.types.is_datetime64_any_dtype(self.data._dataname.index):
                self.data._dataname.index = pd.to_datetime(self.data._dataname.index)

        # 初始化核心 SMA 策略邏輯，產生買/賣訊號
        self.sma_core = SmaCore(self.p.short_period, self.p.long_period)
        self.order = None

        # 記錄策略啟動時的初始資金
        self.initial_capital = self.broker.getcash()

        # 初始化累計變數：買入次數、賣出次數、累計手續費（以 USDT 計算）
        self.buy_count = 0
        self.sell_count = 0
        self.total_fee_usdt = 0.0

        # 在圖表上加入短期與長期 SMA 指標線
        self.sma_short_indicator = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period, plotname="SMA Short"
        )
        self.sma_long_indicator = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period, plotname="SMA Long"
        )

    def next(self):
        """
        每根新的 K 線到來時呼叫：
          1. 取得當前收盤價。
          2. 使用核心 SMA 模組更新價格並獲得交易訊號 ("buy" 或 "sell")。
          3. 根據訊號與條件判斷是否下單：
             - 買入：必須空倉且現金足夠（至少有初始資金 * buy_pct）。
             - 賣出：必須持有部位。
        """
        current_price = self.data.close[0]
        signal = self.sma_core.update(current_price)

        # 若尚有未完成的訂單，則本次不進行動作
        if self.order:
            return

        # 處理買入訊號
        if signal == "buy":
            if not self.position:  # 確保空倉狀態
                available_cash = self.broker.getcash()  # 當前可用現金
                buy_amount = (
                    self.initial_capital * self.p.buy_pct
                )  # 每次買入預計使用的金額
                if available_cash >= buy_amount:
                    # 計算買入數量：使用買入金額除以當前價格，允許小數部份
                    order_size = buy_amount / current_price
                    self.order = self.buy(size=order_size, exectype=bt.Order.Market)
                    self.log(
                        f"Buy order placed: size={order_size:.6f} at price {current_price:.2f} using {buy_amount:.2f} USDT"
                    )
                else:
                    self.log(
                        f"Buy signal received, but available cash {available_cash:.2f} is less than required {buy_amount:.2f}"
                    )
            else:
                self.log(
                    "Buy signal received, but already in position. No action taken."
                )

        # 處理賣出訊號
        elif signal == "sell":
            if self.position:  # 確保持有部位
                self.order = self.close(exectype=bt.Order.Market)
                self.log(f"Sell order placed at price {current_price:.2f}")
            else:
                self.log("Sell signal received, but no position held. No action taken.")

    def notify_order(self, order):
        """
        當訂單狀態改變時呼叫：
          - 若訂單成交，計算手續費，並更新累計統計數據（買入/賣出次數、總手續費）。
          - 若訂單取消或失敗，則記錄相應訊息。
        """
        if order.status in [order.Completed]:
            if order.isbuy():
                # 買入手續費：以成交的加密幣數量計算，結果為 BTC，換算成 USDT = 成交價格 × (taker_fee_rate × 成交數量)
                fee_btc = self.p.taker_fee_rate * order.executed.size
                fee_usdt = fee_btc * order.executed.price
                self.total_fee_usdt += fee_usdt
                self.buy_count += 1
                self.log(
                    f"Buy executed: raw size={order.executed.size:.6f}, fee={fee_btc:.6f} BTC (~{fee_usdt:.2f} USDT), net={(order.executed.size - fee_btc):.6f} BTC at price {order.executed.price:.2f}"
                )
            elif order.issell():
                # 賣出手續費：以成交金額計算，手續費 = maker_fee_rate × (成交價格 × 成交數量)
                trade_value = order.executed.price * order.executed.size
                fee_usdt = self.p.maker_fee_rate * trade_value
                self.total_fee_usdt += fee_usdt
                self.sell_count += 1
                self.log(
                    f"Sell executed: size={order.executed.size:.6f} at price {order.executed.price:.2f}, trade value={trade_value:.2f} USDT, fee={fee_usdt:.2f} USDT"
                )
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order canceled/margin/rejected")
            self.order = None

    def log(self, txt, dt=None):
        """
        簡單的 log 函數：將訊息列印出來，這裡使用 strftime 格式化日期與時間。
        """
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {txt}")

    def get_result(self):
        """
        返回策略運行結束時的統計資訊，包括：
         - 初始資金
         - 最終資產（USDT，透過 broker.getvalue() 獲得）
         - 獲利與獲利率
         - 買入次數與賣出次數
         - 總手續費（USDT）
         - 短期 SMA 週期、長期 SMA 週期、買入使用比例 (buy_pct)
        """
        final_value = self.broker.getvalue()
        profit = final_value - self.initial_capital
        profit_rate = (profit / self.initial_capital) * 100.0
        return {
            "initial_capital": self.initial_capital,
            "final_value": final_value,
            "profit": profit,
            "profit_rate": profit_rate,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "total_fee_usdt": self.total_fee_usdt,
            "short_period": self.p.short_period,
            "long_period": self.p.long_period,
            "buy_pct": self.p.buy_pct,
        }
