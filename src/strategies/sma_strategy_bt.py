"""
檔案名稱: sma_strategy_bt.py

說明:
  此程式為一個策略回測程式，同時也具備主程式功能，可以直接執行進行回測。
  程式流程如下：
    1. 利用 DataLoader 從指定資料來源（例如透過 CCXT）下載歷史 K 線資料，
       並將資料轉換成適合 Backtrader 使用的格式（將 "datetime" 欄位轉換為 datetime 型態並設為索引）。
    2. 建立 Backtrader 的資料 Feed 與策略 (SmaCoreStrategy)，並依照設定的參數執行回測。
    3. 回測完成後，透過策略物件提供的 get_result 方法取得績效報告，
       亦可選擇繪製圖表或儲存回測報告。

使用方法:
  1. 確認已安裝所需第三方套件（例如 backtrader, pandas, okx-api 等），
     並且確保同一目錄下有 sma_core 模組及 utils/data_loader.py（用於下載歷史資料）。
  2. 根據需求修改參數設定：
       - exchange_config、start_time 與 end_time 決定歷史資料來源與區間。
       - 回測參數包括 init_capital（初始資金）、short_period、long_period、buy_pct 等。
  3. 執行本程式：
         python sma_strategy_bt.py
  4. 程式執行後將會進行單次或批次回測（可依 __main__ 區塊中設定切換），
     並輸出回測結果與報告檔案（CSV 格式）。

注意事項:
  - 此程式僅供策略回測與測試使用，回測結果僅供參考，勿直接應用於正式交易。
  - 請確認歷史資料的正確性與完整性，並根據回測需求調整策略參數。
  - 若使用批次回測，回測完成後會將結果依 profit_rate 由大到小排序並儲存報告至指定資料夾。

版本: 1.0
建立日期: 2025-03-21
作者: [ChatGPT o3-mini-high]
"""

import backtrader as bt
from sma_core import SmaCore  # 引入核心 SMA 計算邏輯
import pandas as pd
import logging
import os
import time

# -----------------------
# 設定 logger
# -----------------------
logger = logging.getLogger("SmaCoreStrategyLogger")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_filename = f"results/log/sma_strategy_bt_{timestamp}.log"
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

        # 初始化累計變數：買入次數、賣出次數、累計手續費（以 USDT 計算）與累計實現盈虧
        self.buy_count = 0
        self.sell_count = 0
        self.total_fee_usdt = 0.0
        self.cum_pnl = 0.0  # 累計已實現損益

        # 加入短期與長期 SMA 指標線
        self.sma_short_indicator = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period, plotname="SMA Short"
        )
        self.sma_long_indicator = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period, plotname="SMA Long"
        )

    def start(self):
        """
        回測啟動時記錄初始狀態
        """
        self.log("啟動回測交易")
        self.log("交易幣對: BTC-USDT")
        # 取得初始現金與持倉（預設空倉）
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
        每根新的 K 線到來時呼叫：
          1. 寫入該根 K 線的 OHLCV 資料至 log。
          2. 取得當前收盤價，並利用核心 SMA 模組更新價格，獲得交易訊號 ("buy" 或 "sell")。
          3. 根據訊號判斷是否下單：
             - 買入：需空倉且現金足夠（至少有初始資金 * buy_pct）。
             - 賣出：需持有部位。
        """
        ohlcv_str = (
            f"OHLCV => Open: {self.data.open[0]:.2f}, "
            f"High: {self.data.high[0]:.2f}, "
            f"Low: {self.data.low[0]:.2f}, "
            f"Close: {self.data.close[0]:.2f}, "
            f"Volume: {self.data.volume[0]}"
        )
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
        當訂單狀態改變時呼叫：
          - 若訂單成交，計算手續費、更新統計數據，並印出目前總資產、買賣次數與資產變化。
          - 若訂單取消或失敗，則記錄相應訊息。
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

            # 印出目前總資產明細 (現金 + 持倉換算成 USDT)
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
        self.log(f"buy_pct: {result['buy_pct']}")
        self.log(f"short_period: {result['short_period']}")
        self.log(f"long_period: {result['long_period']}")

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
            "buy_pct": self.p.buy_pct,
            "short_period": self.p.short_period,
            "long_period": self.p.long_period,
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
            "buy_pct": self.p.buy_pct,
            "short_period": self.p.short_period,
            "long_period": self.p.long_period,
        }


def run_strategy(
    data, init_capital=10000, short_period=5, long_period=20, buy_pct=0.3, plot=False
):
    """
    建立 Backtrader 引擎，設定資料與策略，執行回測並返回策略績效報告。

    參數:
      data (pd.DataFrame): 歷史 K 線資料，必須包含 'datetime', 'open', 'high', 'low', 'close', 'volume'
      init_capital (float): 初始資金，預設 10000 USDT
      short_period (int): 短期 SMA 週期
      long_period (int): 長期 SMA 週期
      buy_pct (float): 每次買入所使用的初始資金比例
      plot (bool): 是否繪製回測圖表

    返回:
      dict: 策略回測的績效報告
    """
    datafeed = bt.feeds.PandasData(dataname=data)

    cerebro = bt.Cerebro()
    cerebro.adddata(datafeed)
    cerebro.addstrategy(
        SmaCoreStrategy,
        short_period=short_period,
        long_period=long_period,
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


# -------------------------------------------------------------------
# __main__ 區塊 - 回測主程式 (可直接執行此檔案進行回測)
# -------------------------------------------------------------------
if __name__ == "__main__":
    # 載入歷史資料
    import sys
    import os

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils.data_loader import DataLoader  # 確保 utils/data_loader.py 可用

    # ============= Parameters Start Here ====================
    # Dataloader
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "1h"
    START_TIME = "2025-01-01 00:00:00"
    END_TIME = "2025-04-14 23:59:59"
    # SMA Backtest
    INIT_CAPITAL = 1000
    SHORT_PERIOD = 10
    LONG_PERIOD = 120
    BUY_PERCENTATGE = 0.1
    # Multi
    SHORTS = [5, 10, 20, 60, 120, 240]
    LONGS = [5, 10, 20, 60, 120, 240]
    # Mode
    RUN_SINGLE_BT = True
    RUN_MULTI_BT = False
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

    # 產生統一的資料表名稱
    tablename = DataLoader.generate_table_name(exchange_config)
    print(f"使用的資料表名稱: {tablename}")

    # -------------------------------------------------------------------
    # 回測執行 - 可選擇單次回測或批次回測
    # -------------------------------------------------------------------

    # 若需要單次回測，請將以下 if 條件設為 True
    if RUN_SINGLE_BT:
        run_strategy(
            df,
            init_capital=INIT_CAPITAL,
            short_period=SHORT_PERIOD,
            long_period=LONG_PERIOD,
            buy_pct=BUY_PERCENTATGE,
            plot=True,
        )

    # 批次回測示範：遍歷不同的 SMA 參數組合
    if RUN_MULTI_BT:
        results = []
        for short in SHORTS:
            for long in LONGS:
                if short < long:
                    result = run_strategy(
                        df,
                        init_capital=INIT_CAPITAL,
                        short_period=short,
                        long_period=long,
                        buy_pct=BUY_PERCENTATGE,
                        plot=False,
                    )
                    results.append(result)
        df_result = pd.DataFrame(results)
        df_result_sorted = df_result.sort_values(by="profit_rate", ascending=False)
        print(df_result_sorted)
        save_report("results/report", tablename, df_result_sorted)
