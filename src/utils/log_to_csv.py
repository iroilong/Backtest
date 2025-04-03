import re
import pandas as pd
from datetime import datetime, timedelta

# 指定 log 檔路徑
log_file = r"results/log/sma_strategy_demo_20250325_021932.log"
data = []

# 用正則表達式找出行中 "接收到行情" 的時間與價格
pattern = r"接收到行情：([\d\- :]+), 市價: ([\d\.]+)"

last_timestamp = None
last_ticker = None

with open(log_file, "r", encoding="utf-8") as f:
    for line in f:
        match = re.search(pattern, line)
        if match:
            ts_str = match.group(1).strip()  # 取得行情的 timestamp 字串
            price = float(match.group(2))  # 取得市價
            try:
                current_timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"解析時間錯誤 {ts_str}: {e}")
                continue

            # 規則1：如果與上一筆時間相同，捨棄新的 ticker
            if last_timestamp is not None and current_timestamp == last_timestamp:
                continue

            # 規則3：如果當前的 timestamp 小於上一筆，則捨棄該 ticker
            if last_timestamp is not None and current_timestamp < last_timestamp:
                continue

            # 規則2：如果時間間隔超過 1 秒，補上中間缺失的秒數，
            # 補上的 tick 的所有欄位都以上一筆 ticker 的 close 值為準
            if last_timestamp is not None:
                gap = int((current_timestamp - last_timestamp).total_seconds())
                if gap > 1:
                    for i in range(1, gap):
                        missing_timestamp = last_timestamp + timedelta(seconds=i)
                        data.append(
                            {
                                "datetime": missing_timestamp,
                                "open": last_ticker["close"],
                                "high": last_ticker["close"],
                                "low": last_ticker["close"],
                                "close": last_ticker["close"],
                                "volume": 0,
                            }
                        )

            # 將當前 ticker 加入資料：
            # open 採用前一筆 ticker 的 close (若存在)，否則使用當前市價，
            # h, l, c 都使用當前市價
            current_ticker = {
                "datetime": current_timestamp,
                "open": last_ticker["close"] if last_ticker is not None else price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
            }
            data.append(current_ticker)
            last_timestamp = current_timestamp
            last_ticker = current_ticker

# 轉成 DataFrame 並依 timestamp 排序（雖然 log 檔通常是順序的）
df = pd.DataFrame(data)
df.sort_values("datetime", inplace=True)

# 存成 CSV 檔，供 backtrader 載入
df.to_csv("data/csv_data/ohlcv.csv", index=False)

print("轉換完成，OHLCV 資料已儲存至 data/csv_data/ohlcv.csv")
