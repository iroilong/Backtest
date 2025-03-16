import asyncio
import websockets
import json


async def subscribe_ticker():
    uri = "wss://ws.okx.com:8443/ws/v5/public"
    async with websockets.connect(uri) as websocket:
        # 訂閱 BTC/USDT 的 ticker 資料
        subscription_msg = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": "BTC-USDT"}],
        }
        await websocket.send(json.dumps(subscription_msg))
        print("訂閱訊息已發送，等待數據...")

        # 持續接收並顯示來自 OKX 的數據
        while True:
            response = await websocket.recv()
            print(response)


asyncio.get_event_loop().run_until_complete(subscribe_ticker())

exit()


################### API ####################
"""
apikey = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
secretkey = "D5CBAFD3B4B13991EED0BB0669A73582"
IP = ""
password = "Okx7513#"
備註名 = "DemoOKX"
權限 = "讀取/提現/交易"'
"""
############################################


import ccxt
import pandas as pd

# 設定OKX沙盒環境
exchange = ccxt.okx(
    {
        "apiKey": "87561929-75c9-4ec2-928d-caf03c1cc7a9",
        "secret": "D5CBAFD3B4B13991EED0BB0669A73582",
        "password": "Okx7513#",
        "enableRateLimit": True,
    }
)
exchange.set_sandbox_mode(True)  # 啟用模擬環境

# 查詢帳戶餘額
balance = exchange.fetch_balance()
# print(balance)

# 假設 balance 為 fetch_balance 回傳的字典
assets = []
for asset in balance["free"]:
    assets.append(
        {
            "asset": asset,
            "free": balance["free"][asset],
            "used": balance["used"][asset],
            "total": balance["total"][asset],
        }
    )

df = pd.DataFrame(assets)
print(df)
symbol = "BTC/USDT"

# 取得當前市場價格資訊
ticker = exchange.fetch_ticker(symbol)

# 輸出當前價格（last 為最近成交價格）
print("BTC 當前市價：", ticker["last"])

exit()


try:
    trades = exchange.fetch_my_trades(symbol)
    # for trade in trades:
    #     print(trade)
except Exception as e:
    print("查詢成交記錄失敗:", e)

try:
    orders = exchange.fetchOpenOrders(symbol)
    # for order in orders:
    #     print(order)
except Exception as e:
    print("查詢訂單記錄失敗:", e)

# 抽取關鍵欄位
formatted_trades = []
for t in trades:
    dt = pd.to_datetime(t.get("datetime"), utc=True).tz_convert("Asia/Taipei")
    formatted_trades.append(
        {
            "交易ID": t.get("id"),
            "訂單ID": t.get("order"),
            "時間": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "交易對": t.get("symbol"),
            "方向": t.get("side"),
            "價格": t.get("price"),
            "數量": t.get("amount"),
            "成交額": t.get("cost"),
            "手續費": t.get("fee", {}).get("cost"),
            "手續費幣別": t.get("fee", {}).get("currency"),
        }
    )

# 利用 Pandas 建立 DataFrame 並印出
df = pd.DataFrame(formatted_trades)
print(df)


try:
    orders = exchange.fetchClosedOrders(symbol)
    # for order in orders:
    #     print(order)
except Exception as e:
    print("查詢訂單記錄失敗:", e)

# 抽取關鍵欄位
formatted_trades = []
for t in trades:
    dt = pd.to_datetime(t.get("datetime"), utc=True).tz_convert("Asia/Taipei")

    formatted_trades.append(
        {
            "交易ID": t.get("id"),
            "訂單ID": t.get("order"),
            "時間": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "交易對": t.get("symbol"),
            "方向": t.get("side"),
            "價格": t.get("price"),
            "數量": t.get("amount"),
            "成交額": t.get("cost"),
            "手續費": t.get("fee", {}).get("cost"),
            "手續費幣別": t.get("fee", {}).get("currency"),
        }
    )

# 利用 Pandas 建立 DataFrame 並印出
df = pd.DataFrame(formatted_trades)
print(df)
