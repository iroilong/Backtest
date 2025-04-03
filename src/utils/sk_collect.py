import asyncio
import websockets
import json
import csv
import logging
import os
import sys
import signal
from datetime import datetime, timezone, timedelta

trades = []
ohlcv_log = []

# === 設定輸出路徑與檔名 ===
output_dir = "./data/misc"
os.makedirs(output_dir, exist_ok=True)
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_file_path = os.path.join(output_dir, f"ohlcv_log_{timestamp_str}.csv")
log_file_path = os.path.join(output_dir, f"okx_raw_{timestamp_str}.log")

# === Logging 原始推播資料 ===
logging.basicConfig(
    filename=log_file_path,
    filemode="a",
    format="%(asctime)s - %(message)s",
    level=logging.INFO,
)


def generate_ohlcv(trades_window):
    if not trades_window:
        return None
    open_price = float(trades_window[0]["price"])
    close_price = float(trades_window[-1]["price"])
    high_price = max(float(t["price"]) for t in trades_window)
    low_price = min(float(t["price"]) for t in trades_window)
    volume = sum(float(t["size"]) for t in trades_window)
    return {
        "timestamp": trades_window[0]["timestamp"],
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }


def handle_trade(msg):
    global trades
    for trade in msg:
        ts = int(int(trade["ts"]) / 1000)
        trades.append({"timestamp": ts, "price": trade["px"], "size": trade["sz"]})
        print(f"[TICK] {trade['px']} size:{trade['sz']} @ {ts}")


async def kline_loop():
    global trades, ohlcv_log
    while True:
        now = int(datetime.now(timezone.utc).timestamp())
        dt_str = (
            datetime.fromtimestamp(now - 1, tz=timezone.utc) + timedelta(hours=8)
        ).strftime("%Y-%m-%d %H:%M:%S")
        window = [t for t in trades if t["timestamp"] == now - 1]
        ohlcv = generate_ohlcv(window)

        if ohlcv:
            print(
                f"[KLINE {dt_str}] O:{ohlcv['open']} H:{ohlcv['high']} L:{ohlcv['low']} C:{ohlcv['close']} V:{ohlcv['volume']}"
            )
            ohlcv_log.append(
                [
                    dt_str,
                    round(ohlcv["open"], 6),
                    round(ohlcv["high"], 6),
                    round(ohlcv["low"], 6),
                    round(ohlcv["close"], 6),
                    round(ohlcv["volume"], 6),
                ]
            )
        else:
            print(f"[KLINE {dt_str}] No trades.")
            last_price = ohlcv_log[-1][1] if ohlcv_log else 0
            ohlcv_log.append(
                [dt_str, last_price, last_price, last_price, last_price, 0]
            )

        trades = [t for t in trades if t["timestamp"] >= now - 1]
        await asyncio.sleep(1)


async def listen_trades():
    uri = "wss://ws.okx.com:8443/ws/v5/public"
    while True:
        try:
            async with websockets.connect(
                uri, ping_interval=20, ping_timeout=10
            ) as websocket:
                sub_param = {
                    "op": "subscribe",
                    "args": [{"channel": "trades", "instId": "BTC-USDT"}],
                }
                await websocket.send(json.dumps(sub_param))
                print("✅ Subscribed to BTC-USDT trades")
                async for message in websocket:
                    logging.info(message)
                    msg = json.loads(message)
                    if "data" in msg:
                        handle_trade(msg["data"])
        except Exception as e:
            print(f"⚠️ WebSocket error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


def save_to_csv():
    with open(csv_file_path, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for row in ohlcv_log:
            formatted_row = [row[0]] + [f"{x:.6f}" for x in row[1:]]
            writer.writerow(formatted_row)
    print(f"💾 Saved {len(ohlcv_log)} rows to {csv_file_path}")


async def csv_backup_loop():
    while True:
        await asyncio.sleep(60)
        save_to_csv()


def handle_exit(sig, frame):
    print("\n🛑 KeyboardInterrupt detected. Saving final CSV...")
    save_to_csv()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


async def main():
    await asyncio.gather(listen_trades(), kline_loop(), csv_backup_loop())


asyncio.run(main())
