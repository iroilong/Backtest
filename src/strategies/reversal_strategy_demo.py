import okx.Trade as Trade

# 🔐 API 設定（請改成你自己的）
apikey = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
secretkey = "D5CBAFD3B4B13991EED0BB0669A73582"
IP = ""
password = "Okx7513#"

API_KEY = apikey
API_SECRET = secretkey
PASSPHRASE = password
flag = "1"  # 模擬帳戶填 "1"，實盤填 "0"

# 建立 Trade API 實例
tradeAPI = Trade.TradeAPI(API_KEY, API_SECRET, PASSPHRASE, False, flag)
result = tradeAPI.place_order(
    instId="BTC-USDT",
    tdMode="cash",
    side="buy",
    ordType="limit",
    px="50000",
    sz="0.001",
    tgtCcy="base_ccy",
    attachAlgoOrds=[
        {
            "tpTriggerPx": "92000",
            "tpOrdPx": "-1",
            "slTriggerPx": "48000",
            "slOrdPx": "-1",
        }
    ],
)

print(result)
