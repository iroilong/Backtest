import os
import pandas as pd
import backtrader as bt
import time


# ------------------------------------------------------------------------------
# 固定金額 Sizer：每次下單都使用初始資金的固定百分比來買入 BTC
# ------------------------------------------------------------------------------
class FixedAmountSizer(bt.Sizer):
    """
    FixedAmountSizer 根據「初始資金」的固定百分比計算下單金額。
    例如：初始資金為 10000 USDT，若設定 fixed_percent=50，
    則每次買入下單金額為 5000 USDT，再根據當前價格計算可買入的 BTC 數量。

    參數:
      fixed_percent (int): 買入時使用初始資金的百分比 (0~100)
    """

    params = (("fixed_percent", 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        initial_cash = self.broker.startingcash  # 初始資金
        order_value = initial_cash * self.p.fixed_percent / 100.0
        # 若當前可用現金不足，則全部使用現有現金
        if cash < order_value:
            order_value = cash
        # 根據當前價格計算可買入/賣出的 BTC 數量
        size = order_value / data.close[0]
        return size


# ------------------------------------------------------------------------------
# MakerTakerCommission：手續費模型
# ------------------------------------------------------------------------------
class MakerTakerCommission(bt.CommInfoBase):
    """
    本類別定義手續費計算接口，因為我們在 notify_order() 中手動計算佣金，
    所以此處直接回傳 0，避免重複計算。
    """

    def getcommission(self, size, price):
        return 0


# ------------------------------------------------------------------------------
# 策略：連續陰線後反轉買入策略（Bearish Reversal Strategy）
# ------------------------------------------------------------------------------
class ConsecutiveBearishBuyMarketStrategy(bt.Strategy):
    """
    此策略的主要流程：
      1. 連續累計陰線 (收盤價低於開盤價)，當累計數達到設定門檻 (consecutive) 時，
         進入觸發狀態（triggered），等待下一根陽線。
      2. 當觸發狀態下出現第一根陽線 (收盤價高於開盤價)，即以市價單買入，
         並根據實際成交價計算止盈 (take_profit_pct) 與止損 (stop_loss_pct) 價。
      3. 持倉期間，每根 K 線檢查是否達到止盈或止損目標，若達到，則以市價平倉（全部賣出）。
      4. 賣出後重置狀態，等待下一輪條件達成。

    參數:
      consecutive (int): 連續陰線門檻 (例如 3)
      take_profit_pct (float): 止盈百分比 (例如 3 表示 +3%)
      stop_loss_pct (float): 止損百分比 (例如 -2 表示 -2%)
    """

    params = (
        ("consecutive", 3),
        ("take_profit_pct", 3),
        ("stop_loss_pct", -2),
    )

    def __init__(self):
        # 用於累計連續陰線的根數
        self.streak_count = 0
        # 觸發旗標：達到連續陰線門檻後開始等待陽線買入
        self.triggered = False
        self.order = None
        self.buy_count = 0
        self.sell_count = 0
        # 累計手續費
        self.total_commission = 0.0
        # 紀錄每次交易事件 (如成交價格、佣金、目標止盈/止損等)
        self.event_log = []
        # 旗標：是否已持倉
        self.in_trade = False

    def next(self):
        """
        每根 K 線 (Bar) 執行一次：
          - 若已有持倉，則檢查是否達到止盈或止損目標，若達成則平倉。
          - 若無持倉，累計陰線數，當累計達到門檻後，進入等待第一根陽線狀態，
            一旦第一根陽線出現，立即以市價單買入。
        """
        # (1) 若持倉中，檢查止盈或止損
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

        # (2) 若無持倉，檢查連續陰線累計與等待陽線進場
        if not self.in_trade:
            # 尚未觸發：累計陰線
            if not self.triggered:
                if self.data.close[0] < self.data.open[0]:
                    self.streak_count += 1
                    if self.streak_count == self.p.consecutive:
                        self.triggered = True
                        self.log(
                            f"觸發條件達成：連續陰線數 = {self.streak_count}，開始等待第一根陽線進場"
                        )
                else:
                    # 陽線出現但未達門檻則重置累計
                    self.streak_count = 0
            else:
                # 已觸發：等待第一根陽線
                if self.data.close[0] > self.data.open[0]:
                    self.log(
                        f"第一根陽線出現，進場買入，成交價 {self.data.close[0]:.2f}"
                    )
                    self.buy(exectype=bt.Order.Market, info={"entry_log": True})
                    self.in_trade = True
                    self.triggered = False
                    self.streak_count = 0
                # 若持續陰線，則保持觸發狀態

    def notify_order(self, order):
        """
        當訂單狀態改變時被呼叫。
        此函數負責：
          1. 計算手續費 (根據 maker/taker 率)
          2. 從 broker 中扣除當次手續費，並印出更新後的剩餘資金
          3. 印出買入/賣出成交詳細資訊，並更新交易統計數據。
        """
        if order.status == order.Completed:
            # 計算成交金額
            trade_value = abs(order.executed.size * order.executed.price)
            # 根據 maker/taker 設定費率：taker 0.100%，maker 0.080%
            if order.info.get("maker_or_taker", "taker") == "maker":
                commrate = 0.0008
            else:
                commrate = 0.0010
            commission = trade_value * commrate

            order.executed.comm = commission
            self.total_commission += commission

            # 取得當前可用現金，扣除手續費，再更新現金餘額
            remaining_cash = self.broker.getcash()
            new_cash = remaining_cash - commission
            self.broker.set_cash(new_cash)

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
                    f"BUY EXECUTED, Price: {entry_price:.2f}, Size: {order.executed.size:.5f}, "
                    f"Comm: {commission:.2f}, 剩餘資金: {self.broker.getcash():.2f}, "
                    f"止盈: {target_profit:.2f}, 止損: {target_stop:.2f}"
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
                    f"SELL EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.5f}, "
                    f"Comm: {commission:.2f} ({exit_reason}), 剩餘資金: {self.broker.getcash():.2f}"
                )
                self.in_trade = False

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("訂單取消/保證金不足/拒絕")
            self.in_trade = False

        # 清除 order 物件，避免下一輪重複使用
        self.order = None

    def log(self, txt, dt=None):
        """
        自訂的 log 函數，用於印出當前時間與訊息，方便觀察回測過程。
        """
        dt = dt or self.data.datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {txt}")

    def get_result(self):
        """
        回傳策略運行後的統計結果，包括：
          - buy_count: 買入次數
          - sell_count: 賣出次數
          - total_commission: 累計手續費
          - consecutive: 使用的連續陰線門檻
          - tp_pct: 止盈百分比（參數值）
          - sl_pct: 止損百分比（參數值）

        注意：因為每次交易時已從現金中扣除手續費，
              所以最終 profit 可用最終資金減去初始資金計算。
        """
        return {
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "total_commission": self.total_commission,
            "consecutive": self.p.consecutive,
            "tp_pct": self.p.take_profit_pct,
            "sl_pct": self.p.stop_loss_pct,
        }


# ------------------------------------------------------------------------------
# 單次回測函數
# ------------------------------------------------------------------------------
def run_bearish_reversal_backtest(
    engine, data, init_cash, percent, consecutive, tp_pct, sl_pct, plot=True
):
    """
    執行單次「連續陰線後反轉買入」策略的回測。

    Args:
        engine: 回測引擎實例 (例如 backtest_engines.backtrader_engine.BacktraderEngine)
        data: pandas DataFrame 格式的歷史 K 線資料，必須包含欄位：
              datetime, open, high, low, close, volume, symbol
        init_cash (float): 初始資金 (例如 10000 USDT)
        percent (float): 每次買入佔用初始資金的百分比 (0 ~ 100)
        consecutive (int): 連續陰線門檻 (例如 3)
        tp_pct (float): 止盈百分比 (正數，例如 3 表示 +3%)
        sl_pct (float): 止損百分比 (負數，例如 -2 表示 -2%)
        plot (bool): 是否在回測結束後繪圖 (預設 True)

    Returns:
        dict: 回測結果，包括最終資金、買賣次數、累計手續費及策略參數等資訊。
              最終 profit = final_value - initial_capital (因為手續費已隨交易扣除)
    """
    result = engine.run_strategy(
        strategy=ConsecutiveBearishBuyMarketStrategy,  # 使用本策略
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


# ------------------------------------------------------------------------------
# 多組回測函數
# ------------------------------------------------------------------------------
def run_bearish_reversal_backtest_multi(
    engine, data, init_cashes, percents, consecutives, tp_pct_list, sl_pct_list
):
    """
    執行多組參數組合的回測，方便批次測試不同初始資金、下單比例、連續陰線門檻、止盈與止損值等。

    Args:
        engine: 回測引擎實例 (例如 BacktraderEngine)
        data: pandas DataFrame 格式的歷史 K 線資料
        init_cashes (list[float]): 多種初始資金列表 (例如 [10000, 20000])
        percents (list[float]): 每次買入使用現金比例的列表 (例如 [50, 100])
        consecutives (list[int]): 多組連續陰線門檻 (例如 [3, 5])
        tp_pct_list (list[float]): 多組止盈百分比 (例如 [2, 3, 5])
        sl_pct_list (list[float]): 多組止損百分比 (例如 [-1, -2, -3])

    Returns:
        pandas.DataFrame: 每次回測結果彙整成的表格，其中包含最終資金、獲利率、買賣次數、累計手續費及所使用的策略參數，
                          並印出總耗時。
    """
    results = []
    total_start = time.time()  # 紀錄批次回測開始時間

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
                            plot=False,  # 批次回測時通常不繪圖
                        )
                        # 將本次回測使用的參數加入結果字典中
                        result.update(
                            {
                                "init_cash": init_cash,
                                "percent": percent,
                                "consecutive": consecutive,
                                "tp_pct": tp_pct,
                                "sl_pct": sl_pct,
                            }
                        )
                        results.append(result)

    total_elapsed = time.time() - total_start
    print(f"多組回測總耗時: {total_elapsed:.2f} 秒")

    return pd.DataFrame(results)
