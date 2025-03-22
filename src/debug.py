import re
import pandas as pd

# 範例 raw data，實際上你可以從檔案讀取
raw_lines = []
with open("./results/sma_strategy_bt_20250321_030146.log", "r") as fo:
    raw_lines = fo.read().splitlines()


# raw_lines = [
#     "2025-03-21 03:03:19 - INFO - 2024-10-01 05:05:00 - OHLCV => Open: 63804.00, High: 63810.00, Low: 63790.00, Close: 63790.00, Volume: 20.34584",
#     "2025-03-21 03:03:19 - INFO - 2024-10-01 05:06:00 - OHLCV => Open: 63790.00, High: 63790.01, Low: 63742.53, Close: 63750.00, Volume: 24.84501",
#     "2025-03-21 03:03:19 - INFO - 2024-10-01 05:07:00 - OHLCV => Open: 63750.00, High: 63764.00, Low: 63749.93, Close: 63757.01, Volume: 11.64213",
#     "2025-03-21 03:03:19 - INFO - 2024-10-01 05:07:00 - Sell order placed at price 63757.01",
#     "2025-03-21 03:03:19 - INFO - 2024-10-01 05:08:00 - Sell executed: size=-0.126167 at price 63757.01, trade value=-8044.03 USDT, fee=-6.44 USDT",
#     "2025-03-21 03:03:19 - INFO - 2024-10-01 05:08:00 - OHLCV => Open: 63757.01, High: 63780.00, Low: 63757.00, Close: 63775.47, Volume: 12.97564",
#     # ... 其它 raw data 行
# ]

# 使用正則表達式匹配符合格式的 OHLCV log 行
pattern = r".* - (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - OHLCV => Open: ([\d.]+), High: ([\d.]+), Low: ([\d.]+), Close: ([\d.]+), Volume: ([\d.]+)"

data = []
for line in raw_lines[:10]:
    m = re.match(pattern, line)
    if m:
        # 取得 OHLCV 時間與各數值
        timestamp_str = m.group(1)
        open_val = float(m.group(2))
        high_val = float(m.group(3))
        low_val = float(m.group(4))
        close_val = float(m.group(5))
        volume_val = float(m.group(6))
        data.append(
            {
                "datetime": pd.to_datetime(timestamp_str),
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "volume": volume_val,
                "symbol": "DOGE/USDT",  # 固定 symbol，可根據實際需求調整
            }
        )

# 建立 DataFrame 並設定 datetime 為索引，依時間排序
df = pd.DataFrame(data)
df = df.set_index("datetime").sort_index()

print(df)
df.to_csv("./results/sma_strategy_bt_20250321_030146_1s.csv")
