import asyncio
import websockets
import json
import csv
import os
import signal
import sys
import logging
from datetime import datetime

# === 初始化變數 ===
candles = []
last_ts = None
prev_candle = None

# === 建立資料夾與檔案路徑 ===
output_dir = "./data/misc"
os.makedirs(output_dir, exist_ok=True)
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

csv_file_path = os.path.join(output_dir, f"candle1m_{timestamp_str}.csv")
log_file_path = os.path.join(output_dir, f"candle1m_{timestamp_str}.log")

# === 同時輸出到 log 檔案與終端機 ===
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(log_formatter)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

# === 建立 CSV 標頭 ===
with open(csv_file_path, mode="w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["ts", "o", "h", "l", "c", "vol", "volCcy"])


# === 每根 candle 收盤時存入 CSV ===
def save_candle(candle):
    with open(csv_file_path, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(candle)


# === 程式結束時一次性儲存所有收盤 candle ===
def save_all():
    logging.info(f"Saving {len(candles)} candles to CSV...")
    with open(csv_file_path, mode="a", newline="") as f:
        writer = csv.writer(f)
        for row in candles:
            writer.writerow(row)
    logging.info(f"Finished writing to CSV: {csv_file_path}")


# === Ctrl+C 安全結束處理 ===
def handle_exit(sig, frame):
    logging.info("Ctrl+C detected. Saving all candles and exiting...")
    save_all()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


# === 處理每筆推播資料 ===
def handle_candle(data):
    global last_ts, candles, prev_candle
    for d in data:
        ts, o, h, l, c, vol, vol_ccy = d
        ts_int = int(ts)

        logging.info(
            f"[LIVE] ts={ts} o={o} h={h} l={l} c={c} vol={vol} volCcy={vol_ccy}"
        )

        if ts_int != last_ts:
            if last_ts is not None and prev_candle:
                candles.append(prev_candle)
                logging.info(f"Closed candle: {prev_candle}")
                save_candle(prev_candle)
            last_ts = ts_int

        prev_candle = [ts, o, h, l, c, vol, vol_ccy]


# === WebSocket 主程式 ===
async def subscribe_candle():
    uri = "wss://ws.okx.com:8443/ws/v5/public"
    async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as websocket:
        sub_msg = {
            "op": "subscribe",
            "args": [{"channel": "candle1m", "instId": "BTC-USDT"}],
        }
        await websocket.send(json.dumps(sub_msg))
        logging.info("Subscribed to BTC-USDT candle1m")

        async for message in websocket:
            msg = json.loads(message)
            if "data" in msg:
                handle_candle(msg["data"])


# === 啟動主程式 ===
asyncio.run(subscribe_candle())
