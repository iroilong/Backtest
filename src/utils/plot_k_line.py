import os
import sqlite3
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# ---------------------------
# 參數設定
backtest_start = pd.to_datetime("2025-03-11 00:00:00")
backtest_end = pd.to_datetime("2025-03-11 23:59:59")
db_path = os.path.join("data", "binance_BTC_USDT_5m.sqlite")
ma_periods = [5, 10, 20]  # 移動平均週期

# 取得資料庫名稱（不含副檔名）
db_name = os.path.splitext(os.path.basename(db_path))[0]


# ---------------------------
# 從資料庫中讀取資料 (假設資料表名稱為 kline)
def load_data(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"資料庫不存在：{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM kline ORDER BY datetime ASC", conn)
    finally:
        conn.close()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    if "openinterest" not in df.columns:
        df["openinterest"] = 0
    return df


df = load_data(db_path)
df = df.loc[backtest_start:backtest_end]
if df.empty:
    raise ValueError("指定回測區間內無資料")

# ---------------------------
# 計算移動平均線
for period in ma_periods:
    df[f"MA{period}"] = df["close"].rolling(window=period).mean()

# 建立額外圖層用於 MA 線
apds = [
    mpf.make_addplot(df[f"MA{period}"], panel=0, width=1.0, ylabel=f"MA{period}")
    for period in ma_periods
]

# ---------------------------
# 使用 mplfinance 畫出 K 線圖與 MA 線，並回傳 Figure 與 Axes
fig, axes = mpf.plot(
    df,
    type="candle",
    style="charles",
    addplot=apds,
    volume=True,
    title=f'Candlestick Chart ({db_name}): {backtest_start.strftime("%Y-%m-%d")} to {backtest_end.strftime("%Y-%m-%d")}',
    ylabel="Price",
    returnfig=True,
)

# ---------------------------
# 手動新增圖例
# 手動指定 K 線上漲與下跌的顏色
up_color = "green"
down_color = "red"

candlestick_legend = [
    Line2D([0], [0], color=up_color, lw=2, label="Green Candle"),
    Line2D([0], [0], color=down_color, lw=2, label="Red Candle"),
]

# 為 MA 線指定顏色 (依序使用 blue, orange, purple)
ma_colors = ["blue", "orange", "purple"]
ma_legend = [
    Line2D([0], [0], color=ma_colors[i % len(ma_colors)], lw=1.5, label=f"MA{period}")
    for i, period in enumerate(ma_periods)
]

# 合併所有圖例項目
all_legend = candlestick_legend + ma_legend

# 將圖例新增到第一個主圖軸上
axes[0].legend(handles=all_legend, loc="upper left")

plt.show()
