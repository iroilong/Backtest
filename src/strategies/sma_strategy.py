import os
import pandas as pd
import backtrader as bt
import time


# ------------------------------------------------------------------------------
# FractionalSizer：根據可用資金與當前價格計算下單數量（允許小數）
# ------------------------------------------------------------------------------
class FractionalSizer(bt.Sizer):
    """
    FractionalSizer 根據當前可用資金 (cash) 與當前價格來計算買入 BTC 的數量。

    計算邏輯：
      - 若為買單 (isbuy=True)：使用當前可用現金乘以設定的百分比，再除以當前價格，
        得到可以買入的 BTC 數量。
      - 若為賣單 (isbuy=False)：直接返回目前持有的部位數量，確保賣出時全數平倉。

    參數:
      percents (int): 買單時使用的現金百分比 (0~100)。
    """

    params = (("percents", 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            # 計算買入金額 = cash * (percents / 100)
            size = (cash * self.p.percents / 100) / data.close[0]
            return size
        else:
            # 賣單時返回目前持倉數量，確保全數平倉
            position = self.broker.getposition(data)
            return position.size


# ------------------------------------------------------------------------------
# MakerTakerCommission：手續費模型
# ------------------------------------------------------------------------------
class MakerTakerCommission(bt.CommInfoBase):
    """
    由於我們在 notify_order() 中自訂了手續費計算，
    因此此處先直接回傳 0，避免重複計算。
    """

    def getcommission(self, size, price):
        return 0


# ------------------------------------------------------------------------------
# SMA 策略：利用短期與長期 SMA 的交叉判斷買賣訊號
# ------------------------------------------------------------------------------
class SMAStrategy(bt.Strategy):
    """
    SMAStrategy 利用短期與長期簡單移動平均線 (SMA) 的交叉訊號來決定買賣時機：
      - 當短期 SMA 向上穿越長期 SMA 時 (金叉)，產生買入訊號；
      - 當短期 SMA 向下穿越長期 SMA 時 (死叉)，產生賣出訊號。

    此策略同時統計買入與賣出次數，以及累計的手續費。

    參數:
      short_period (int): 短期 SMA 的週期，預設為 5
      long_period (int): 長期 SMA 的週期，預設為 20
    """

    params = (("short_period", 5), ("long_period", 20))

    def __init__(self):
        # 建立短期與長期 SMA 指標
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period
        )
        # CrossOver 指標：正值代表金叉（買入訊號），負值代表死叉（賣出訊號）
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
        self.order = None  # 用來儲存當前訂單
        self.buy_count = 0  # 買入次數
        self.sell_count = 0  # 賣出次數
        self.total_commission = 0.0  # 累計手續費

    def next(self):
        """
        每一根 K 線 (Bar) 呼叫一次 next()：
          - 若已有待處理訂單，則不執行新判斷；
          - 若目前無持倉，且 SMA 的交叉指標顯示金叉（crossover > 0），則下市價單買入；
          - 若目前持倉中，且 SMA 的交叉指標顯示死叉（crossover < 0），則下市價單平倉。
        """
        if self.order:
            return

        # 無持倉時檢查買入訊號
        if not self.position:
            if self.crossover > 0:
                order = self.buy(exectype=bt.Order.Market)
                order.info["maker_or_taker"] = "taker"
                self.order = order
                print(
                    f"Buy Order Submitted at {self.datas[0].datetime.date(0)}, Price: {self.datas[0].close[0]:.2f}"
                )
        else:
            # 有持倉時檢查賣出訊號
            if self.crossover < 0:
                order = self.close(exectype=bt.Order.Market)
                order.info["maker_or_taker"] = "taker"
                self.order = order
                print(
                    f"Sell Order Submitted at {self.datas[0].datetime.date(0)}, Price: {self.datas[0].close[0]:.2f}"
                )

    def notify_order(self, order):
        """
        當訂單狀態改變時會被呼叫：
          - 若訂單成交，計算手續費並手動扣除該筆費用，
            同時印出成交價格、成交量、手續費與扣費後剩餘資金。
          - 若訂單被取消、保證金不足或拒絕，則印出相關訊息。
        """
        if order.status == order.Completed:
            trade_value = abs(order.executed.size * order.executed.price)
            # 根據 maker/taker 判斷不同手續費率：
            # taker 費率為 0.100%，maker 費率為 0.080%
            if order.info.get("maker_or_taker", "taker") == "maker":
                commrate = 0.0008
            else:
                commrate = 0.0010
            commission = trade_value * commrate
            order.executed.comm = commission
            self.total_commission += commission

            # 從 broker 取得當前現金，並扣除當次手續費
            remaining_cash = self.broker.getcash()
            new_cash = remaining_cash - commission
            self.broker.set_cash(new_cash)

            if order.isbuy():
                self.buy_count += 1
                print(
                    f"BUY EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.5f}, "
                    f"Comm: {commission:.2f}, 剩餘資金: {self.broker.getcash():.2f}"
                )
            else:
                self.sell_count += 1
                print(
                    f"SELL EXECUTED, Price: {order.executed.price:.2f}, Size: {order.executed.size:.5f}, "
                    f"Comm: {commission:.2f}, 剩餘資金: {self.broker.getcash():.2f}"
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print("Order Canceled/Margin/Rejected")
        self.order = None

    def get_result(self):
        """
        回傳策略運行後的統計結果，包含：
          - buy_count: 買入次數
          - sell_count: 賣出次數
          - total_commission: 累計手續費
          - short_period: 短期 SMA 週期
          - long_period: 長期 SMA 週期

        最終 profit 可由回測計算：
          profit = final_value - initial_capital
        (因為手續費已隨交易從現金中扣除)
        """
        return {
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "total_commission": self.total_commission,
            "short_period": self.p.short_period,
            "long_period": self.p.long_period,
        }


# ------------------------------------------------------------------------------
# 單次 SMA 策略回測函數（不依賴外部 engine）
# ------------------------------------------------------------------------------
def run_sma_backtest(data, init_cash, percent, short_period, long_period, plot=True):
    """
    執行單次 SMA 策略回測，不依賴 engine 檔案，
    直接利用 Backtrader 完成回測流程。

    Args:
        data: pandas DataFrame 格式的歷史 K 線資料，必須包含欄位：
              datetime, open, high, low, close, volume, symbol
        init_cash (float): 初始資金 (例如 10000 USDT)
        percent (float): 每次下單時用於買入的現金比例 (0~100)
        short_period (int): 短期 SMA 的週期 (例如 5)
        long_period (int): 長期 SMA 的週期 (例如 20)
        plot (bool): 是否在回測後繪製圖表 (預設 True)

    Returns:
        dict: 回測結果，包括最終資金、獲利率、買賣次數、累計手續費及策略參數等資訊。
              (profit = final_value - initial_capital)
    """
    t0 = time.time()
    cerebro = bt.Cerebro()

    # 設定 Broker 參數
    cerebro.broker.setcash(init_cash)
    # 此處 commission 設為 0，因策略中自行計算手續費
    cerebro.broker.setcommission(commission=0.0)

    # 加入下單數量設定：FractionalSizer
    cerebro.addsizer(FractionalSizer, percents=percent)

    # 加入策略
    cerebro.addstrategy(SMAStrategy, short_period=short_period, long_period=long_period)

    # 處理資料：確保有 datetime 欄位，並轉換成 datetime 格式及設為 index
    if "datetime" not in data.columns:
        if data.index.name == "datetime":
            data = data.reset_index()
        else:
            raise KeyError("資料中必須包含 'datetime' 欄位或索引名稱為 'datetime'")
    if not pd.api.types.is_datetime64_any_dtype(data["datetime"]):
        data["datetime"] = pd.to_datetime(data["datetime"])
    data.set_index("datetime", inplace=True)

    datafeed = bt.feeds.PandasData(dataname=data)
    cerebro.adddata(datafeed)

    cerebro_run = cerebro.run()
    elapsed = time.time() - t0

    if plot:
        cerebro.plot()

    final_value = cerebro.broker.getvalue()
    profit = final_value - init_cash
    profit_rate = (profit / init_cash) * 100.0

    # 取得策略實例並獲取自訂結果
    strat_instance = cerebro_run[0]
    custom_result = {}
    if hasattr(strat_instance, "get_result") and callable(strat_instance.get_result):
        custom_result = strat_instance.get_result()

    result = {
        "backtest_start_date": data.index.min().strftime("%Y-%m-%d %H:%M:%S"),
        "backtest_end_date": data.index.max().strftime("%Y-%m-%d %H:%M:%S"),
        "starting_cash": init_cash,
        "final_value": final_value,
        "profit": profit,
        "profit_rate": profit_rate,
        "elapsed": elapsed,
    }
    result.update(custom_result)
    return result


# ------------------------------------------------------------------------------
# 多組 SMA 策略回測函數
# ------------------------------------------------------------------------------
def run_sma_backtest_multi(data, init_cashes, percents, short_periods, long_periods):
    """
    執行多組參數組合的 SMA 策略回測，
    方便批次測試不同初始資金、下單比例以及均線週期的組合。

    Args:
        data: pandas DataFrame 格式的歷史資料
        init_cashes (list[float]): 初始資金列表 (例如 [10000, 20000])
        percents (list[float]): 每次下單現金比例列表 (例如 [50, 100])
        short_periods (list[int]): 短期 SMA 週期列表 (例如 [5, 10])
        long_periods (list[int]): 長期 SMA 週期列表 (例如 [20, 30])

    Returns:
        pandas.DataFrame: 每次回測結果彙整成的表格，
                          包含最終資金、獲利率、買賣次數、累計手續費及使用的策略參數。
    """
    results = []
    for init_cash in init_cashes:
        for percent in percents:
            for short_period in short_periods:
                for long_period in long_periods:
                    # 確保短期 SMA 週期小於長期 SMA 週期
                    if short_period >= long_period:
                        continue
                    result = run_sma_backtest(
                        data, init_cash, percent, short_period, long_period, plot=False
                    )
                    result["percent"] = percent
                    result["short_period"] = short_period
                    result["long_period"] = long_period
                    results.append(result)
    return pd.DataFrame(results)
