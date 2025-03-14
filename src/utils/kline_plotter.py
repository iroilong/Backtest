import pandas as pd
import mplfinance as mpf


def plot_candlestick_chart(df: pd.DataFrame, title: str = "Candlestick Chart"):
    """
    使用 mplfinance 繪製 K 線圖。假設 df 的格式為：
        datetime, open, high, low, close, volume, symbol
    其中 datetime 為字串或 datetime 型態。
    """
    # 確保 datetime 欄位為 datetime 型態
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"])
    # 將 datetime 設定成索引
    df.set_index("datetime", inplace=True)

    # 使用 mplfinance 畫圖，這裡同時顯示成交量
    mpf.plot(df, type="candle", volume=True, title=title)
