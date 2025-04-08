import okx.MarketData as MarketData
from datetime import datetime, timedelta, timezone
import pandas as pd
import os
import time


# === 將台北時間字串轉成 UTC timestamp（毫秒）===
def taipei_to_utc_timestamp(dt_str):
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    taipei_dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return int(taipei_dt.astimezone(timezone.utc).timestamp() * 1000)


# === 將 UTC timestamp（ms）轉回台北時間字串 ===
def utc_to_taipei_str(ts_ms):
    utc_dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
    taipei_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
    return taipei_dt.strftime("%Y-%m-%d %H:%M:%S")


# === 參數：你只需要填台北時間即可 ===
INST_ID = "BTC-USDT"
BAR_SIZE = "1s"
START_TIME_TAIPEI = "2025-04-04 00:00:00"
END_TIME_TAIPEI = "2025-04-04 00:01:00"

# === 自動轉成 UTC timestamp 給 API 使用 ===
after = taipei_to_utc_timestamp(START_TIME_TAIPEI)
before = taipei_to_utc_timestamp(END_TIME_TAIPEI)

# === 初始化 OKX API ===
market = MarketData.MarketAPI(flag="0")

# === 抓資料分頁 ===
all_data = []
while True:
    resp = market.get_history_candlesticks(
        instId=INST_ID, bar=BAR_SIZE, after=str(after), limit="100"
    )
    data = resp.get("data", [])
    if not data:
        break

    all_data.extend(data)
    last_ts = int(data[-1][0])
    print(utc_to_taipei_str(last_ts))
    # if last_ts >= before:
    k = after - 200000
    print(last_ts)
    print(k)
    if last_ts <= after - 200000:
        break
    after = last_ts + 1
    time.sleep(0.1)

# === 建立 DataFrame 並加上台北時間欄位 ===
df = pd.DataFrame(
    all_data,
    columns=["ts", "o", "h", "l", "c", "vol", "volCcy", "volCcyQuote", "confirm"],
)
df.insert(0, "datetime", df["ts"].apply(utc_to_taipei_str))

# === 儲存成 CSV ===
output_dir = "./data/misc"
os.makedirs(output_dir, exist_ok=True)
filename = f"okx_{INST_ID.replace('-', '')}_{BAR_SIZE}_{START_TIME_TAIPEI.replace(':','').replace(' ', '_')}.csv"
filepath = os.path.join(output_dir, filename)

df.to_csv(filepath, index=False)
print(f"✅ Saved {len(df)} rows to {filepath}")
