#!/usr/bin/env python3
"""
檔案名稱: reversal_strategy_bt.py

說明:
  此程式為 Reversal 策略回測程式，模仿 sma_strategy_bt.py 結構，
  使用 reversal_core 模組提供的核心邏輯來判斷交易訊號，
  並以 Backtrader 進行回測。策略流程為：
    1. 累計連續陰線（收盤價低於開盤價）達到設定門檻後，
       進入觸發狀態等待第一根陽線 (收盤價高於開盤價) 出現，
       進而以市價買入並設定止盈/止損。
    2. 持倉期間，若價格觸及止盈或止損點則平倉，並重置狀態。

使用方法:
  1. 確保 reversal_core.py 與此檔案位於同一目錄或可被 import 的路徑下。
  2. 根據需求修改回測參數與資料來源設定。
  3. 執行本程式 (例如 python reversal_strategy_bt.py) 即可開始回測。
"""

import backtrader as bt
from reversal_core import ReversalCore  # 引入 Reversal 核心策略邏輯
import pandas as pd
import logging
import os
import time

# -----------------------
# 設定 logger
# -----------------------
logger = logging.getLogger("ReversalCoreStrategyLogger")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_filename = f"results/log/reversal_strategy_bt_{timestamp}.log"
    fh = logging.FileHandler(log_filename, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)


class ReversalCoreStrategy(bt.Strategy):
    params = (
        ("consecutive_bear_threshold", 3),  # 連續陰線門檻 (例如 3 根)
        ("take_profit_pct", 3),  # 止盈百分比 (例如 +3%)
        ("stop_loss_pct", -2),  # 止損百分比 (例如 -2%)
        ("buy_pct", 0.3),  # 每次買入所使用初始資金比例 (例如 0.3 表示 30%)
        ("taker_fee_rate", 0.001),  # 買入手續費率 (吃單，0.1%)
        ("maker_fee_rate", 0.0008),  # 賣出手續費率 (掛單，0.08%)
    )

    def __init__(self):
        # 檢查資料格式，確保索引為 datetime 型態
        if hasattr(self.data, "_dataname") and isinstance(
            self.data._dataname, pd.DataFrame
        ):
            if not pd.api.types.is_datetime64_any_dtype(self.data._dataname.index):
                self.data._dataname.index = pd.to_datetime(self.data._dataname.index)

        # 初始化 Reversal 策略核心 (注意 ReversalCore 的 __init__ 必須正確命名)
        self.reversal_core = ReversalCore(
            self.p.consecutive_bear_threshold,
            self.p.take_profit_pct,
            self.p.stop_loss_pct,
        )
        self.order = None

        # 記錄初始資金與統計數據
        self.initial_capital = self.broker.getcash()
        self.buy_count = 0
        self.sell_count = 0
        self.total_fee_usdt = 0.0
        self.cum_pnl = 0.0

        # 用來判斷是否已 log 過門檻訊息
        self.threshold_logged = False
        # 用來判斷是否已 log 觸發狀態後的第一根陽線
        self.first_bull_logged = False

    def start(self):
        """回測啟動時記錄初始狀態"""
        self.log("啟動回測交易")
        self.log("交易幣對: BTC-USDT")
        cash = self.broker.getcash()
        position = self.getposition(self.data)
        btc_qty = position.size if position else 0.0
        current_price = self.data.close[0]
        btc_value = btc_qty * current_price
        total_assets = cash + btc_value
        self.log("目前手上幣對數量及其市值:")
        self.log(f"BTC: {btc_qty:.6f} BTC（價值 ${btc_value:.2f} USDT）")
        self.log(f"USDT: {cash:.6f} USDT")
        self.log(f"BTC-USDT 總價值 ${total_assets:.3f} USDT")

    def next(self):
        """
        每根 K 線到來時執行：
          1. 記錄該根 K 線的 OHLCV 資料（並於 volume 後附上該根 K 線為陰線或陽線）。
          2. 將當前 K 線資料組合為字典傳入 reversal_core.update() 取得訊號 ("buy" 或 "sell")。
          3. 根據訊號及當前持倉狀態判斷是否下市價單。
        """
        # 判斷該根 K 線為陰線或陽線
        candle_type = "平盤"
        if self.data.close[0] < self.data.open[0]:
            candle_type = "陰線"
        elif self.data.close[0] > self.data.open[0]:
            candle_type = "陽線"

        # 記錄當前 K 線的 OHLCV 資料 (並加上 candle_type)
        ohlcv_str = (
            f"OHLCV => Open: {self.data.open[0]:.2f}, "
            f"High: {self.data.high[0]:.2f}, "
            f"Low: {self.data.low[0]:.2f}, "
            f"Close: {self.data.close[0]:.2f}, "
            f"Volume: {self.data.volume[0]} [{candle_type}]"
        )
        self.log(ohlcv_str, to_print=False)

        # 組合當前 K 線資料成字典格式 (供 reversal_core 使用)
        candle = {
            "open": self.data.open[0],
            "high": self.data.high[0],
            "low": self.data.low[0],
            "close": self.data.close[0],
        }
        # 取得 reversal_core 所產生的交易訊號
        signal = self.reversal_core.update(candle)

        # 當不在觸發狀態時，重置 threshold_logged 與 first_bull_logged 旗標
        if not self.reversal_core.triggered:
            self.threshold_logged = False
            self.first_bull_logged = False

        # 如果達到門檻且尚未 log，則記錄訊息
        if self.reversal_core.triggered and not self.threshold_logged:
            self.log(
                f"連續{self.reversal_core.bear_count}根陰線 -> 達到門檻，進入觸發狀態，等待第一根陽線"
            )
            self.threshold_logged = True

        # 若尚有未處理的訂單則不再下單
        if self.order:
            return

        current_price = self.data.close[0]
        # 處理買入訊號：僅在空倉且現金足夠時執行
        if signal == "buy":
            if not self.position:
                available_cash = self.broker.getcash()
                buy_amount = self.initial_capital * self.p.buy_pct
                if available_cash >= buy_amount:
                    order_size = buy_amount / current_price
                    self.order = self.buy(size=order_size, exectype=bt.Order.Market)
                    # log 下單時附上止盈與止損價訊息
                    self.log(
                        f"Buy order placed: size={order_size:.6f} at price {current_price:.2f} using {buy_amount:.2f} USDT. "
                        f"止盈價(+{self.p.take_profit_pct}%): {self.reversal_core.take_profit_price:.2f}, "
                        f"止損價({self.p.stop_loss_pct}%): {self.reversal_core.stop_loss_price:.2f}"
                    )
                    # 若還未 log 過第一根陽線，則 log 該訊息
                    if not self.first_bull_logged:
                        self.log("此為觸發狀態後的第一根陽線")
                        self.first_bull_logged = True
                else:
                    self.log(
                        f"Buy signal received, but available cash {available_cash:.2f} is less than required {buy_amount:.2f}"
                    )
            else:
                self.log(
                    "Buy signal received, but already in position. No action taken."
                )

        # 處理賣出訊號：僅在持有部位時執行
        elif signal == "sell":
            if self.position:
                self.order = self.close(exectype=bt.Order.Market)
                self.log(f"Sell order placed at price {current_price:.2f}")
            else:
                self.log("Sell signal received, but no position held. No action taken.")

    def notify_order(self, order):
        """
        當訂單狀態變化時呼叫：
          - 若訂單成交，計算手續費、更新交易次數及記錄執行細節。
          - 並印出目前總資產狀態與累計盈虧。
        """
        if order.status in [order.Completed]:
            if order.isbuy():
                fee_btc = self.p.taker_fee_rate * order.executed.size
                fee_usdt = fee_btc * order.executed.price
                self.total_fee_usdt += fee_usdt
                self.buy_count += 1
                self.log(
                    f"Buy executed: raw size={order.executed.size:.6f}, fee={fee_btc:.6f} BTC (~{fee_usdt:.2f} USDT), net={(order.executed.size - fee_btc):.6f} BTC at price {order.executed.price:.2f}. 買單總次數: {self.buy_count}"
                )
            elif order.issell():
                trade_value = order.executed.price * order.executed.size
                fee_usdt = self.p.maker_fee_rate * trade_value
                self.total_fee_usdt += fee_usdt
                self.sell_count += 1
                self.log(
                    f"Sell executed: size={order.executed.size:.6f} at price {order.executed.price:.2f}, trade value={trade_value:.2f} USDT, fee={fee_usdt:.2f} USDT. 賣單總次數: {self.sell_count}"
                )
            self.order = None

            # 印出目前總資產狀態
            current_price = order.executed.price
            position = self.getposition(self.data)
            btc_qty = position.size if position else 0.0
            cash = self.broker.getcash()
            btc_value = btc_qty * current_price
            total_assets = cash + btc_value
            self.log("目前手上幣對數量及其市值:")
            self.log(f"BTC: {btc_qty:.6f} BTC（價值 ${btc_value:.2f} USDT）")
            self.log(f"USDT: {cash:.6f} USDT")
            self.log(f"BTC-USDT 總價值 ${total_assets:.2f} USDT")

            asset_change = total_assets - self.initial_capital
            change_str = (
                f"+{asset_change:.2f}" if asset_change >= 0 else f"{asset_change:.2f}"
            )
            self.log(f"資產變化: {change_str} USDT")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order canceled/margin/rejected")
            self.order = None

    def notify_trade(self, trade):
        """
        當交易平倉時呼叫，更新累計實現盈虧，並印出策略累積盈虧。
        """
        if trade.isclosed:
            self.cum_pnl += trade.pnl
            self.log(
                f"📊 已實現損益（策略本身盈虧）: {self.cum_pnl:.2f} USDT", to_print=True
            )

    def stop(self):
        """
        回測結束時記錄最終策略結果。
        """
        result = self.get_result()
        self.log("**************************************************")
        self.log("交易結束，統計結果如下：")
        self.log(f"start_time: {result['start_time']}")
        self.log(f"end_time: {result['end_time']}")
        self.log(f"initial_capital: {result['initial_capital']}")
        self.log(f"final_value: {result['final_value']:.2f}")
        self.log(f"profit: {result['profit']:.2f}")
        self.log(f"profit_rate: {result['profit_rate']:.2f}%")
        self.log(f"buy_count: {result['buy_count']}")
        self.log(f"sell_count: {result['sell_count']}")
        self.log(f"total_fee_usd: {result['total_fee_usdt']:.2f}")
        self.log(f"consecutive_bear_threshold: {result['consecutive_bear_threshold']}")
        self.log(f"take_profit_pct: {result['take_profit_pct']}")
        self.log(f"stop_loss_pct: {result['stop_loss_pct']}")

    def get_result(self):
        """
        返回策略回測結束時的統計資訊，包括：
          - 回測資料開始與結束時間
          - 初始資金、最終資產、獲利及獲利率
          - 買入次數、賣出次數、總手續費
          - 策略參數設定
        """
        if hasattr(self.data, "_dataname") and isinstance(
            self.data._dataname, pd.DataFrame
        ):
            start_time = self.data._dataname.index[0]
            end_time = self.data._dataname.index[-1]
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
            "consecutive_bear_threshold": self.p.consecutive_bear_threshold,
            "take_profit_pct": self.p.take_profit_pct,
            "stop_loss_pct": self.p.stop_loss_pct,
        }

    def log(self, txt, dt=None, to_print=True):
        """
        將訊息寫入 log 檔並可選擇印出至終端機。

        參數:
          txt (str): 要記錄的訊息。
          dt (datetime, optional): 時間戳，預設使用當前資料的時間。
          to_print (bool): 是否印出訊息至終端機，預設 True。
        """
        dt = dt or self.datas[0].datetime.datetime(0)
        message = f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {txt}"
        if to_print:
            print(message)
        logger.info(message)


def run_strategy(
    data,
    init_capital=10000,
    consecutive_bear_threshold=3,
    take_profit_pct=3,
    stop_loss_pct=-2,
    buy_pct=0.3,
    plot=False,
):
    """
    建立 Backtrader 引擎，設定資料與策略，執行回測並返回策略績效報告。

    參數:
      data (pd.DataFrame): 歷史 K 線資料，必須包含 'datetime', 'open', 'high', 'low', 'close', 'volume'
      init_capital (float): 初始資金，預設 10000 USDT
      consecutive_bear_threshold (int): 連續陰線門檻
      take_profit_pct (float): 止盈百分比
      stop_loss_pct (float): 止損百分比
      buy_pct (float): 每次買入所使用的初始資金比例
      plot (bool): 是否繪製回測圖表

    返回:
      dict: 策略回測的績效報告
    """
    datafeed = bt.feeds.PandasData(dataname=data)
    cerebro = bt.Cerebro()
    cerebro.adddata(datafeed)
    cerebro.addstrategy(
        ReversalCoreStrategy,
        consecutive_bear_threshold=consecutive_bear_threshold,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        buy_pct=buy_pct,
    )
    cerebro.broker.setcash(init_capital)
    results = cerebro.run()
    strategy_instance = results[0]
    result = strategy_instance.get_result()
    print("策略結果：", result)
    if plot:
        cerebro.plot()
    return result


def save_report(dir_path: str, filename: str, df: pd.DataFrame):
    """
    將回測結果 DataFrame 儲存為 CSV 檔。

    參數:
      dir_path (str): 儲存的資料夾路徑。
      filename (str): 檔案基本名稱。
      df (pd.DataFrame): 回測結果 DataFrame。
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{filename}_report_{timestamp}.csv"
    filepath = os.path.join(dir_path, filename)
    df.to_csv(filepath, index=False)
    print(f"檔案已儲存至 {filepath}")


if __name__ == "__main__":
    # 載入歷史資料
    import sys
    import os

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils.data_loader import DataLoader

    # ============= Parameters Start Here ====================
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "1m"
    START_TIME = "2025-04-01 00:00:00"
    END_TIME = "2025-04-14 23:59:59"
    INIT_CAPITAL = 1000
    # Single
    CONSECUTIVE_BEAR_THRESHOLD = 5
    TAKE_PROFIT_PCT = 6
    STOP_LOSS_PCT = -1
    BUY_PERCENTAGE = 0.1
    # Multi
    CONSECUTIVE_BEAR_THRESHOLDS = [2, 3, 4, 5, 6, 7]
    TAKE_PROFIT_PCTS = [1, 2, 3, 4, 5, 6]
    STOP_LOSS_PCTS = [-1, -2, -3, -4, -5, -6]
    # Mode
    RUN_SINGLE_BT = True
    RUN_MULTI_BT = False
    # RUN_SINGLE_BT = False
    # RUN_MULTI_BT = True
    # ============= Parameters Stop Here ====================

    # 設定交易所參數
    exchange_config = {
        "exchange_id": "binance",
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
    }

    # 建立 DataLoader 實例並下載資料
    data_loader = DataLoader()
    df = data_loader.load_data(
        exchange_config=exchange_config,
        destination="ccxt",
        start_time=START_TIME,
        end_time=END_TIME,
    )

    # 轉換 "datetime" 欄位為 datetime 型態並設為索引
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

    tablename = DataLoader.generate_table_name(exchange_config)
    print(f"使用的資料表名稱: {tablename}")

    # 執行單次回測
    if RUN_SINGLE_BT:
        run_strategy(
            df,
            init_capital=INIT_CAPITAL,
            consecutive_bear_threshold=CONSECUTIVE_BEAR_THRESHOLD,
            take_profit_pct=TAKE_PROFIT_PCT,
            stop_loss_pct=STOP_LOSS_PCT,
            buy_pct=BUY_PERCENTAGE,
            plot=True,
        )

    # 批次回測示範：遍歷不同的 SMA 參數組合
    if RUN_MULTI_BT:
        results = []
        for threshold in CONSECUTIVE_BEAR_THRESHOLDS:
            for profit in TAKE_PROFIT_PCTS:
                for loss in STOP_LOSS_PCTS:
                    result = run_strategy(
                        df,
                        init_capital=INIT_CAPITAL,
                        consecutive_bear_threshold=threshold,
                        take_profit_pct=profit,
                        stop_loss_pct=loss,
                        buy_pct=BUY_PERCENTAGE,
                        plot=False,
                    )
                    results.append(result)
        df_result = pd.DataFrame(results)
        df_result_sorted = df_result.sort_values(by="profit_rate", ascending=False)
        print(df_result_sorted)
        save_report("results/report", f"reversal_{tablename}", df_result_sorted)
