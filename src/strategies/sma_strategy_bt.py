import backtrader as bt
from strategies.sma_core import SmaCore  # 引入核心 SMA 計算邏輯
import pandas as pd
import logging
import os
import time

# 設定 logger
logger = logging.getLogger("SmaCoreStrategyLogger")
logger.setLevel(logging.DEBUG)
# 若尚未有 handler，則加入 FileHandler
if not logger.handlers:
    # 設定 log 檔案名稱，可根據需要調整路徑
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_filename = f"results/sma_strategy_bt_{timestamp}.log"
    fh = logging.FileHandler(log_filename, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)


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

        # 在圖表上加入短期與長期 SMA 指標線，便於觀察
        self.sma_short_indicator = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period, plotname="SMA Short"
        )
        self.sma_long_indicator = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period, plotname="SMA Long"
        )

    def next(self):
        """
        每根新的 K 線到來時呼叫：
          1. 印出該根 K 線的 OHLCV 資料（僅寫入 log 檔，不印出至終端）。
          2. 取得當前收盤價，並用核心 SMA 模組更新價格，獲得交易訊號 ("buy" 或 "sell")。
          3. 根據訊號與條件判斷是否下單：
             - 買入：需空倉且現金足夠（至少有初始資金 * buy_pct）。
             - 賣出：需持有部位。
        """
        # 組合當前 K 線 OHLCV 資料字串
        ohlcv_str = (
            f"OHLCV => Open: {self.data.open[0]:.2f}, "
            f"High: {self.data.high[0]:.2f}, "
            f"Low: {self.data.low[0]:.2f}, "
            f"Close: {self.data.close[0]:.2f}, "
            f"Volume: {self.data.volume[0]}"
        )
        # 將 OHLCV 資料寫入 log 檔，但不在終端機印出
        self.log(ohlcv_str, to_print=False)

        current_price = self.data.close[0]
        signal = self.sma_core.update(current_price)

        if self.order:
            return

        # 處理買入訊號
        if signal == "buy":
            if not self.position:
                available_cash = self.broker.getcash()
                buy_amount = self.initial_capital * self.p.buy_pct
                if available_cash >= buy_amount:
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
            if self.position:
                self.order = self.close(exectype=bt.Order.Market)
                self.log(f"Sell order placed at price {current_price:.2f}")
            else:
                self.log("Sell signal received, but no position held. No action taken.")

    def notify_order(self, order):
        """
        當訂單狀態改變時呼叫，計算手續費並更新統計數據：
          - 若訂單成交，根據買入/賣出分別計算手續費並更新累計數據。
          - 若訂單取消或失敗，則記錄相應訊息。
        """
        if order.status in [order.Completed]:
            if order.isbuy():
                fee_btc = self.p.taker_fee_rate * order.executed.size
                fee_usdt = fee_btc * order.executed.price
                self.total_fee_usdt += fee_usdt
                self.buy_count += 1
                self.log(
                    f"Buy executed: raw size={order.executed.size:.6f}, fee={fee_btc:.6f} BTC (~{fee_usdt:.2f} USDT), net={(order.executed.size - fee_btc):.6f} BTC at price {order.executed.price:.2f}"
                )
            elif order.issell():
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

    def log(self, txt, dt=None, to_print=True):
        """
        log 函數將訊息寫入檔案（透過 logging 模組）並可選擇是否印出至終端機。

        參數:
            txt (str): 要記錄的訊息。
            dt (datetime, optional): 若未提供則使用資料的時間。
            to_print (bool): 是否將訊息印出至終端機，預設 True；若設為 False，則僅寫入 log 檔案。
        """
        dt = dt or self.datas[0].datetime.datetime(0)
        message = f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {txt}"
        if to_print:
            print(message)
        logger.info(message)

    def get_result(self):
        """
        返回策略運行結束時的統計資訊，包括：
        - 回測資料的開始時間 (start_time) 與結束時間 (end_time)
        - 初始資金、最終資產（USDT）、獲利、獲利率
        - 買入次數、賣出次數、總手續費（USDT）
        - 策略參數：短期 SMA 週期、長期 SMA 週期、買入使用比例 (buy_pct)
        """
        # 若資料來源為 pandas DataFrame，則利用索引取得第一筆與最後一筆的時間
        if hasattr(self.data, "_dataname") and isinstance(
            self.data._dataname, pd.DataFrame
        ):
            start_time = self.data._dataname.index[0]
            end_time = self.data._dataname.index[-1]
            # 將 datetime 格式轉為字串
            start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
            end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            start_time_str = None
            end_time_str = None

        final_value = self.broker.getvalue()
        profit = final_value - self.initial_capital
        profit_rate = (profit / self.initial_capital) * 100.0

        return {
            "start_time": start_time_str,
            "end_time": end_time_str,
            "initial_capital": self.initial_capital,
            "final_value": final_value,
            "profit": profit,
            "profit_rate": profit_rate,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "total_fee_usdt": self.total_fee_usdt,
            "buy_pct": self.p.buy_pct,
            "short_period": self.p.short_period,
            "long_period": self.p.long_period,
        }
