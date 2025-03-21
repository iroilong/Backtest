"""
程式概要說明:
    此模組為主程式，主要功能包括：
      1. 利用 DataLoader 從指定資料來源（例如 CCXT）下載歷史 K 線資料。
      2. 將下載後的資料（DataFrame）經由必要的轉換（例如轉換 datetime 欄位並設為索引）。
      3. 建立 Backtrader 的資料 Feed 與策略，並執行回測。
      4. 取得策略回測結果並輸出，亦可選擇繪製圖表。
    此主程式同時支援單次回測與多組參數的批次回測，最後將結果轉換為 DataFrame 並以 profit_rate 排序。
"""

from utils.data_loader import DataLoader
import backtrader as bt
import pandas as pd
from strategies.sma_strategy_bt import SmaCoreStrategy
import os
import time


def run_strategy(
    data, init_captital=10000, short_period=5, long_period=20, buy_pct=0.3, plot=False
):
    """
    run_strategy 函式負責建立 Backtrader 的 Cerebro 引擎，設定資料與策略，
    執行回測並返回策略績效報告。

    參數:
        data (pd.DataFrame): 歷史 K 線資料，資料中必須包含 "datetime", "open", "high", "low", "close", "volume", "symbol"
        init_captital (float): 初始資金，預設 10000 USDT
        short_period (int): 短期 SMA 週期
        long_period (int): 長期 SMA 週期
        buy_pct (float): 每次買入使用初始資金的比例，例如 0.3 表示 30%
        plot (bool): 是否繪製回測圖表

    返回:
        dict: 策略回測的績效報告（包含初始資金、最終資產、獲利、獲利率、買賣次數、總手續費與參數設定）
    """
    # 建立 Backtrader 資料 Feed，傳入已轉換好的 DataFrame
    datafeed = bt.feeds.PandasData(dataname=data)

    cerebro = bt.Cerebro()
    # 加入資料 Feed
    cerebro.adddata(datafeed)
    # 加入 SMA 策略，並設定策略參數
    cerebro.addstrategy(
        SmaCoreStrategy,
        short_period=short_period,
        long_period=long_period,
        buy_pct=buy_pct,
    )
    # 設定初始資金
    cerebro.broker.setcash(init_captital)

    # 執行回測，返回值為包含策略實例的列表
    results = cerebro.run()

    # 若只加入一個策略，直接取第一個策略實例
    strategy_instance = results[0]
    # 從策略實例中獲取績效報告
    result = strategy_instance.get_result()

    print("策略結果：", result)

    if plot:
        cerebro.plot()

    return result


def save_report(dir: str, filename: str, df: pd.DataFrame):
    # 假設 df 是你的 DataFrame
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{filename}_report_{timestamp}.csv"

    # 存檔時不儲存索引（視需求決定）
    filepath = os.path.join(dir, filename)
    df.to_csv(filepath, index=False)
    print(f"檔案已儲存至 {filepath}")


# -------------------------------------------------------------------
# 歷史資料下載
# -------------------------------------------------------------------

# 設定交易所參數 exchange_config
exchange_config = {
    "exchange_id": "binance",
    "symbol": "DOGE/USDT",
    "timeframe": "1h",
}
# 透過 DataLoader 的 generate_table_name 方法產生統一的表格名稱
tablename = DataLoader.generate_table_name(exchange_config)
print(f"使用的資料表名稱: {tablename}")

# 建立 DataLoader 實例
data_loader = DataLoader()

# 下載歷史 K 線資料，指定資料來源、起始與結束時間
start_time = "2024-10-01 00:00:00"
end_time = "2025-04-14 23:59:59"
df = data_loader.load_data(
    exchange_config=exchange_config,
    destination="ccxt",
    start_time=start_time,
    end_time=end_time,
)

# 由於下載下來的資料中 "datetime" 欄位通常為字串，
# 故將 "datetime" 欄位轉換為 datetime 型態並設為索引，
# 這是給 mplfinance 與 Backtrader 資料 Feed 使用的標準格式。
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

# -------------------------------------------------------------------
# 執行策略回測
# -------------------------------------------------------------------

# 呼叫 run_strategy 執行單次回測，並選擇是否繪製圖表
if 0:
    run_strategy(
        df,
        init_captital=10000,
        short_period=5,
        long_period=240,
        buy_pct=0.8,
        plot=True,
    )


# 以下示範批次回測：遍歷不同的短期與長期 SMA 參數組合
if 1:
    shorts = [5, 10, 20, 60]
    longs = [60, 120, 240]

    results = []
    for short in shorts:
        for long in longs:
            if short < long:
                result = run_strategy(
                    df,
                    init_captital=10000,
                    short_period=short,
                    long_period=long,
                    buy_pct=0.8,
                    plot=False,
                )
                results.append(result)  # 將每次回測結果存入列表中

    # 將結果列表轉換為 DataFrame
    df_result = pd.DataFrame(results)

    # 以 profit_rate 由大到小排序結果
    df_result_sorted = df_result.sort_values(by="profit_rate", ascending=False)

    print(df_result_sorted)
    save_report("results", tablename, df_result_sorted)
