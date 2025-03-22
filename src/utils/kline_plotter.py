"""
程式概要說明:
    此模組使用 mplfinance 來繪製 K 線圖，預期讀取的資料格式為：
        datetime, open, high, low, close, volume, symbol
    模組中包含一個函式 plot_candlestick_chart，用於將傳入的 DataFrame 轉換為適合繪圖的格式，
    並以 mplfinance 繪製出 K 線圖。模組也包含一個使用範例，可直接執行本檔案進行測試。
"""

import pandas as pd
import mplfinance as mpf
from data_loader import DataLoader  # 從 data_loader 模組讀取 DataLoader 類別


def plot_candlestick_chart(df: pd.DataFrame, title: str = "Candlestick Chart"):
    """
    使用 mplfinance 繪製 K 線圖。

    參數:
        df (pd.DataFrame): 必須包含欄位 "datetime", "open", "high", "low", "close", "volume", "symbol"
                           其中 "datetime" 可以是字串或 datetime 型態。
        title (str): 圖表標題，預設為 "Candlestick Chart"

    功能:
        1. 確保 "datetime" 欄位為 datetime 型態。
        2. 將 "datetime" 欄位設為 DataFrame 的索引。
        3. 使用 mplfinance 繪製 K 線圖，並同時顯示成交量。
    """
    # 檢查 "datetime" 欄位是否為 datetime 型態，否則轉換
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"])
    # 將 "datetime" 欄位設為索引，mplfinance 要求索引為 DatetimeIndex
    df.set_index("datetime", inplace=True)

    # 使用 mplfinance 畫圖，type="candle" 表示 K 線圖，volume=True 會同時繪製成交量
    mpf.plot(df, type="candle", volume=True, title=title)


# 使用範例
if __name__ == "__main__":
    # 建立 DataLoader 實例，利用它來下載資料
    data_loader = DataLoader()

    # 設定交易所參數 exchange_config
    exchange_config = {
        "exchange_id": "binance",
        "symbol": "DOGE/USDT",
        "timeframe": "1m",
    }

    # 下載資料：設定起始與結束時間
    df = data_loader.load_data(
        exchange_config=exchange_config,
        destination="ccxt",
        start_time="2025-01-01 00:00:00",
        end_time="2025-04-08 15:59:59",
    )

    # 呼叫 plot_candlestick_chart() 繪製 K 線圖
    plot_candlestick_chart(df, title="BTC/USDT 1m Candlestick Chart")
