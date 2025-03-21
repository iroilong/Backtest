import datetime
import time
import logging
import pandas as pd

# 依照你的專案結構調整 import 路徑（此處假設 sma_core.py 與此檔案同層）
from sma_core import SmaCore

# 使用 OKX 官方 API 模組（請先安裝 okx-api）
import okx.Account as Account
import okx.Trade as Trade
import okx.MarketData as MarketData

# -----------------------
# 設定 logger（不需修改）
# -----------------------
logger = logging.getLogger("OkxLiveSandboxLogger")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_filename = f"results/sma_strategy_demo_{timestamp}.log"
    fh = logging.FileHandler(log_filename, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)


class TradeTracker:
    def __init__(self):
        self.trades = []
        self.profit = 0.0

    def record_trade(self, side, price, amount, fee):
        self.trades.append({"side": side, "price": price, "amount": amount, "fee": fee})
        if side == "buy":
            self.profit -= price * amount + fee
        elif side == "sell":
            self.profit += price * amount - fee

    def get_profit(self):
        return self.profit

    def get_total_fee(self):
        return sum(t["fee"] for t in self.trades)


class LiveSandboxTrading:
    """
    程式概要說明:
        利用 OKX 官方 API 在沙盒環境下進行實盤模擬交易：
          - 程式啟動時讀取帳戶餘額，並記錄初始總資產。
          - 每隔一定秒數透過 MarketAPI.get_ticker() 取得最新行情，
            並將市價傳入核心 SMA 模組 (SmaCore) 計算交易訊號，
            當產生買/賣訊號時，下市價單並等待訂單成交。
          - 捕捉 KeyboardInterrupt 優雅退出，並統計交易結果。
    """

    def __init__(
        self,
        symbol="BTC-USDT",
        poll_interval=60,
        buy_usdt=300,
        short_period=5,
        long_period=20,
    ):
        self.start_time = datetime.datetime.now()

        # OKX DEMO API 資訊
        self.api_key = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
        self.secret_key = "D5CBAFD3B4B13991EED0BB0669A73582"
        self.passphrase = "Okx7513#"
        self.symbol = symbol
        flag = "1"  # live trading: 0, demo trading: 1

        self.accountAPI = Account.AccountAPI(
            self.api_key, self.secret_key, self.passphrase, False, flag
        )
        self.tradeAPI = Trade.TradeAPI(
            self.api_key, self.secret_key, self.passphrase, False, flag
        )
        self.marketDataAPI = MarketData.MarketAPI(flag=flag)
        self.tracker = TradeTracker()

        # 取得帳戶資訊並 log 出部分幣種餘額
        self.log("\n\n" + "*" * 50)
        self.log("帳戶資產如下:")
        try:
            balance_data = self.accountAPI.get_account_balance()
            if balance_data.get("code") == "0":
                data = balance_data.get("data", [{}])[0]
                details = data.get("details", [])
                for asset in details:
                    ccy = asset.get("ccy", "N/A")
                    availBal = asset.get("availBal", "0")
                    eqUsd = asset.get("eqUsd", "0")
                    self.log(f"{ccy} = {availBal} ({float(eqUsd):.0f} USD)")
                total_eq = data.get("totalEq", "0")
                self.log(f"帳戶總資產 = {float(total_eq):.0f} USD")
            else:
                self.log(f"取得帳戶資訊失敗: {balance_data}")
        except Exception as e:
            self.log(f"取得帳戶資訊失敗：{e}")

        self.poll_interval = poll_interval
        self.buy_usdt = buy_usdt
        self.strategy = SmaCore(short_period, long_period)
        self.position = None  # 初始無部位

    def place_and_track_market_order(self, side, size, timeout=5):
        order = self.tradeAPI.place_order(
            instId=self.symbol,
            tdMode="cash",
            side=side,
            ordType="market",
            sz=str(size),
            tgtCcy="base_ccy",  # 指定下單數量單位為基礎幣
        )

        if order.get("code") != "0":
            self.log(f"❌ 下單失敗: {order}")
            return None

        order_id = order["data"][0]["ordId"]
        self.log(f"✅ 下單成功，ordId: {order_id}")

        final = self.wait_for_fill_or_cancel(order_id, timeout=timeout)
        if not final:
            self.log("❌ 訂單未成交，已取消")
            return None

        price = float(final["fillPx"])
        amount = float(final["fillSz"])
        fee = abs(float(final["fee"]))
        fee_ccy = final.get("feeCcy", "?")

        # 如果是 BTC 手續費，換算成 USDT 等值
        if fee_ccy.upper() == "BTC":
            fee_usdt = fee * price
            fee_display = f"{fee:.8f} BTC（≈ {fee_usdt:.2f} USDT）"
        else:
            fee_display = f"{fee:.6f} {fee_ccy}"

        self.tracker.record_trade(side, price, amount, fee)
        self.log(
            f"📌 成交：{side.upper()} {amount:.6f} @ {price:.2f}, 手續費: {fee_display}"
        )

        self.log(f"📊 累積盈虧：{self.tracker.get_profit():,.2f} USD")

        return {"price": price, "amount": amount}

    def wait_for_fill_or_cancel(self, order_id, timeout=5):
        start = time.time()
        while time.time() - start < timeout:
            try:
                order = self.tradeAPI.get_order(instId=self.symbol, ordId=order_id)
                data = order.get("data", [])
                if data and data[0].get("state") == "filled":
                    return data[0]
                elif data and data[0].get("state") == "partially_filled":
                    self.log("⚠️ 訂單部分成交中...")
            except Exception as e:
                self.log(f"⚠️ 查詢訂單失敗: {e}")
            time.sleep(1)

        try:
            self.tradeAPI.cancel_order(instId=self.symbol, ordId=order_id)
            self.log(f"🛑 超時未成交，已取消訂單 {order_id}")
        except Exception as e:
            self.log(f"❌ 取消訂單失敗: {e}")
        return None

    def log(self, message, dt=None, to_print=True):
        dt = dt or datetime.datetime.now()
        full_message = f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {message}"
        if to_print:
            print(full_message)
        logger.info(full_message)

    def get_balance_for_pair(self, pair):
        base_currency, quote_currency = pair.upper().split("-")
        balance_data = self.accountAPI.get_account_balance()
        if balance_data.get("code") == "0":
            data = balance_data.get("data", [{}])[0]
            details = data.get("details", [])
            base_amount = 0.0
            base_eqUsd = 0.0
            quote_amount = 0.0
            quote_eqUsd = 0.0
            for asset in details:
                ccy = asset.get("ccy", "").upper()
                availBal = float(asset.get("availBal", "0"))
                eqUsd = float(asset.get("eqUsd", "0"))
                if ccy == base_currency:
                    base_amount = availBal
                    base_eqUsd = eqUsd
                elif ccy == quote_currency:
                    quote_amount = availBal
                    quote_eqUsd = eqUsd
            total_usd_value = base_eqUsd + quote_eqUsd
            return {
                "base_currency": base_currency,
                "base_amount": base_amount,
                "base_eqUsd": base_eqUsd,
                "quote_currency": quote_currency,
                "quote_amount": quote_amount,
                "quote_eqUsd": quote_eqUsd,
                "total_usd_value": total_usd_value,
            }
        else:
            self.log(f"取得帳戶資訊失敗: {balance_data}")
            return None

    def get_simple_ticker(self, api, inst_id="BTC-USDT"):
        result = api.get_ticker(instId=inst_id.upper())
        if result.get("code") != "0":
            self.log("取得 ticker 失敗")
            return None

        ticker = result["data"][0]
        return {
            "timestamp": ticker.get("ts"),
            "instType": ticker.get("instType"),
            "instId": ticker.get("instId"),
            "last": ticker.get("last"),
            "lastSz": ticker.get("lastSz"),
        }

    def run(self):
        self.log("\n\n" + "*" * 50)
        self.log("啟動 OKX 沙盒實盤模擬交易程序")
        self.log(f"交易幣對: {self.symbol}")
        balance_info = self.get_balance_for_pair(self.symbol)
        if balance_info:
            self.log(f"目前手上幣對數量及其市值")

            self.log(
                f"{balance_info['base_currency']}: {balance_info['base_amount']:,.6f} {balance_info['base_currency']}（價值 ${balance_info['base_eqUsd']:,.0f} USD）"
            )
            self.log(
                f"{balance_info['quote_currency']}: {balance_info['quote_amount']:,.6f} {balance_info['quote_currency']}（價值 ${balance_info['quote_eqUsd']:,.0f} USD）"
            )
            self.log(f"BTC+USDT 總價值 ${balance_info['total_usd_value']:,.0f} USD")
            init_total_usd = balance_info["total_usd_value"]
        else:
            self.log("無法獲取帳戶餘額")

        self.buy_count = 0
        self.sell_count = 0
        self.total_fee_usd = 0
        try:
            self.log("\n\n" + "*" * 50)
            self.log("策略開始")

            while True:
                ticker = self.get_simple_ticker(self.marketDataAPI, "BTC-USDT")
                if ticker:
                    timestamp = ticker["timestamp"]
                    tw_time = datetime.datetime.fromtimestamp(
                        int(timestamp) / 1000, tz=datetime.timezone.utc
                    ) + datetime.timedelta(hours=8)
                    current_price = float(ticker["last"])
                    self.log(
                        f"接收到行情：{tw_time.strftime('%Y-%m-%d %H:%M:%S')}, 市價: {current_price:.2f}"
                    )
                signal = self.strategy.update(current_price)
                if signal == "buy":
                    if self.position is None:
                        self.log("核心策略發出買入訊號")
                        amount = self.buy_usdt / current_price
                        trade_result = self.place_and_track_market_order("buy", amount)
                        if trade_result:
                            self.position = {
                                "side": "long",
                                "price": trade_result["price"],
                                "amount": trade_result["amount"],
                            }
                            self.buy_count += 1
                    else:
                        self.log("已持有部位，無法買入")
                elif signal == "sell":
                    if self.position is not None:
                        self.log("核心策略發出賣出訊號")
                        trade_result = self.place_and_track_market_order(
                            "sell", self.position["amount"]
                        )
                        if trade_result:
                            self.position = None
                            self.sell_count += 1
                    else:
                        self.log("無持倉，無法賣出")
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            self.end_time = datetime.datetime.now()
            self.log("\n\n" + "*" * 50)
            self.log("收到 KeyboardInterrupt，程式準備結束")

            # 🔒 程式結束時強制平倉
            if self.position is not None:
                self.log("⚠️ 結束時仍有持倉，準備強制市價平倉...")
                try:
                    trade_result = self.place_and_track_market_order(
                        "sell", self.position["amount"]
                    )
                    if trade_result:
                        self.log("✅ 成功平倉")
                        self.position = None
                        self.sell_count += 1
                except Exception as e:
                    self.log(f"❌ 平倉失敗: {e}")

            total_fee_usd = self.tracker.get_total_fee()

            balance_info = self.get_balance_for_pair(self.symbol)
            if balance_info:
                self.log(f"目前手上幣對數量及其市值")

                self.log(
                    f"{balance_info['base_currency']}: {balance_info['base_amount']:,.6f} {balance_info['base_currency']}（價值 ${balance_info['base_eqUsd']:,.0f} USD）"
                )
                self.log(
                    f"{balance_info['quote_currency']}: {balance_info['quote_amount']:,.6f} {balance_info['quote_currency']}（價值 ${balance_info['quote_eqUsd']:,.0f} USD）"
                )
                self.log(f"BTC+USDT 總價值 ${balance_info['total_usd_value']:,.0f} USD")
                final_total_usd = balance_info["total_usd_value"]
                self.log(f"\n")

            else:
                self.log("無法獲取帳戶餘額")
            profit = final_total_usd - init_total_usd
            profit_rate = (profit / init_total_usd) * 100 if init_total_usd != 0 else 0

            self.log(
                f"📊 已實現損益（策略本身賺了多少）: {self.tracker.get_profit():,.2f} USD"
            )
            self.log(
                f"📊 賬戶總資產變動（幣對總資產變動）: {final_total_usd - init_total_usd:,.2f} USD"
            )

            summary = {
                "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "initial_capital": init_total_usd,
                "final_value": final_total_usd,
                "profit": profit,
                "profit_rate": profit_rate,
                "buy_count": self.buy_count,
                "sell_count": self.sell_count,
                "total_fee_usd": self.total_fee_usd,
                "buy_usdt": self.buy_usdt,
                "short_period": self.strategy.short_period,
                "long_period": self.strategy.long_period,
            }
            self.log("交易結束，統計結果如下：")
            for key, value in summary.items():
                self.log(f"{key}: {value}")
            return


if __name__ == "__main__":
    poll_interval = 1
    buy_usdt = 10
    sandbox = LiveSandboxTrading(
        symbol="BTC-USDT",
        poll_interval=poll_interval,
        buy_usdt=buy_usdt,
        short_period=2,
        long_period=4,
    )
    sandbox.run()
