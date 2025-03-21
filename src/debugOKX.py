import okx.Account as Account
import okx.Trade as Trade
import json

api_key = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
secret_key = "D5CBAFD3B4B13991EED0BB0669A73582"
passphrase = "Okx7513#"

import okx.Account as Account

flag = "1"  # live trading: 0, demo trading: 1

accountAPI = Account.AccountAPI(api_key, secret_key, passphrase, False, flag)

result = accountAPI.get_account_balance()
pretty_json = json.dumps(result, indent=4, ensure_ascii=False)
print(pretty_json)
