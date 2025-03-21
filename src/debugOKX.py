# 使用 OKX 官方 API 模組（請先安裝 okx-api）
import okx.Account as Account
import okx.Trade as Trade
import okx.MarketData as MarketData
import json

api_key = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
secret_key = "D5CBAFD3B4B13991EED0BB0669A73582"
passphrase = "Okx7513#"

import okx.Account as Account

flag = "1"  # live trading: 0, demo trading: 1

accountAPI = Account.AccountAPI(api_key, secret_key, passphrase, False, flag)
tradeAPI = Trade.TradeAPI(api_key, secret_key, passphrase, False, flag)
marketDataAPI = MarketData.MarketAPI(flag=flag)


try:
    balance_data = accountAPI.get_account_balance()
    # 檢查 API 回傳是否成功（code 為 "0" 表示成功）
    if balance_data.get("code") == "0":
        data = balance_data.get("data", [{}])[0]
        details = data.get("details", [])
        for asset in details:
            ccy = asset.get("ccy", "N/A")
            availBal = asset.get("availBal", "0")
            eqUsd = asset.get("eqUsd", "0")
            # 以格式 "幣種 = availBal (eqUsd USDT)" log 出來
            print(f"{ccy} = {availBal} ({float(eqUsd):.0f} USD)")
        total_eq = data.get("totalEq", "0")
        print(f"帳戶總資產 = {float(total_eq):.0f} USD")
    else:
        print(f"取得帳戶資訊失敗: {balance_data}")
except Exception as e:
    print(f"取得帳戶資訊失敗：{e}")


result = accountAPI.get_account_balance()
pretty_json = json.dumps(result, indent=4, ensure_ascii=False)
# print(pretty_json)

symbol = "BTC-USDT"
side = "buy"
amount = 0.00357

#  market order
result = tradeAPI.place_order(
    instId="BTC-USDT",
    tdMode="cash",
    side="buy",
    ordType="market",
    sz="0.001",
    tgtCcy="base_ccy",  # this determines the unit of the sz parameter. base_ccy is the default value
)
print(result)


# order = tradeAPI.place_order(
#     instId=symbol,
#     tdMode="cash",
#     side=side,
#     ordType="market",
#     sz=str(amount),
#     ccy="BTC",
# )
# print(order)
