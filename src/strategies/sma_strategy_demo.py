"""
檔案名稱: sma_strategy_demo.py

說明:
  本程式示範如何利用 OKX 官方 API 在沙盒環境下進行實盤模擬交易，
  並以簡單移動平均（SMA, Simple Moving Average）策略作為核心交易邏輯。
  程式流程如下：
    1. 程式啟動時會讀取並 log 出帳戶餘額資訊（例如 BTC、USDT 等），
       以便確認當前資產狀況。
    2. 程式會以設定的時間間隔定期取得最新行情，
       並將當前市價傳入 SMA 策略模組 (SmaCore) 以計算是否產生買入或賣出訊號。
    3. 當 SMA 策略產生交易訊號時，程式會依據訊號下市價單，
       並使用 OKX API 輪詢訂單狀態直到完全成交或超時後取消訂單。
    4. 成交後，程式會記錄成交價格、數量、手續費（並根據需要將手續費轉換為 USDT 等值），
       並累計計算交易盈虧。
    5. 使用者可透過 Ctrl+C 終止程式，程式中斷時會嘗試強制平倉，並統計與 log 出最終交易結果與盈虧統計。

使用方法:
  1. 確認已安裝必要的第三方套件，如 okx-api、pandas 等，以及同一資料夾下的 sma_core 模組。
  2. 更新程式中 API 金鑰、密鑰與 passphrase 為你的 OKX 沙盒環境帳戶資訊。
  3. 根據需求設定參數：
       - symbol: 交易對 (例如 "BTC-USDT")
       - poll_interval: 輪詢行情間隔（秒）
       - buy_usdt: 每次買入金額（USDT 計價）
       - short_period 與 long_period: SMA 策略參數（短期與長期均線周期）
  4. 執行程式：
         python sma_strategy_demo.py
  5. 程式啟動後會持續取得行情、根據策略發出交易訊號並進行下單，
       使用 Ctrl+C 可中斷程式，中斷後程式會嘗試平倉並輸出交易結果統計。

注意事項:
  - 此程式僅供沙盒環境模擬交易與策略測試使用，請勿直接應用於正式環境，
    以免產生不必要的交易風險與損失。
  - 請確認 OKX 沙盒環境的 API 回應格式與正式環境可能存在差異，根據實際情況進行調整。
  - 若遇到 "Your order should meet or exceed the minimum order amount." 錯誤，
    請確認下單數量計算是否正確，並檢查 tgtCcy 參數是否正確設定（此範例中指定為 "base_ccy"）。
  - 程式在中斷時會嘗試以市價單平倉，請確保平倉動作符合您的策略要求。
  - 請注意交易 API 的調用限制與網路延遲，可能會影響下單與查詢訂單狀態的回應速度。

版本: 1.0
建立日期: 2025-03-21
作者: [你的名字或團隊名稱]
"""

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
    """
    TradeTracker 用於記錄每一筆交易的成交資訊與累積盈虧計算。

    屬性:
        trades (list): 記錄所有交易的列表，每筆交易包含 side, price, amount, fee。
        profit (float): 累積盈虧，買入時扣除成本與手續費，賣出時計算收益並扣除手續費。
    """

    def __init__(self):
        self.trades = []
        self.profit = 0.0

    def record_trade(self, side, price, amount, fee):
        """
        記錄一筆交易，並更新累積盈虧。

        參數:
            side (str): 交易方向，"buy" 或 "sell"。
            price (float): 成交價格。
            amount (float): 成交數量。
            fee (float): 交易手續費。
        """
        self.trades.append({"side": side, "price": price, "amount": amount, "fee": fee})
        if side == "buy":
            self.profit -= price * amount + fee
        elif side == "sell":
            self.profit += price * amount - fee

    def get_profit(self):
        """
        取得目前累積盈虧。

        回傳:
            float: 累積盈虧金額（USD）。
        """
        return self.profit

    def get_total_fee(self):
        """
        計算所有交易累積的手續費總和。

        回傳:
            float: 手續費總和。
        """
        return sum(t["fee"] for t in self.trades)


class LiveSandboxTrading:
    """
    LiveSandboxTrading 類別負責利用 OKX 官方 API 在沙盒環境下進行實盤模擬交易。

    程式流程:
      1. 初始化時讀取帳戶餘額與設定 API 資訊。
      2. 定期取得行情，並將最新市價傳入核心 SMA 模組 (SmaCore) 以取得交易訊號。
      3. 當核心策略發出買入/賣出訊號時，下市價單並等待訂單成交。
      4. 捕捉 KeyboardInterrupt 後，若仍有部位則強制平倉，並統計交易結果。

    參數:
        symbol (str): 交易對，例如 "BTC-USDT"。
        poll_interval (int): 輪詢行情間隔秒數。
        buy_usdt (float): 每次買入金額（以 USDT 計）。
        short_period (int): 核心 SMA 短期參數。
        long_period (int): 核心 SMA 長期參數。
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

        # 初始化 OKX API 物件：帳戶、訂單、市場資料
        self.accountAPI = Account.AccountAPI(
            self.api_key, self.secret_key, self.passphrase, False, flag
        )
        self.tradeAPI = Trade.TradeAPI(
            self.api_key, self.secret_key, self.passphrase, False, flag
        )
        self.marketDataAPI = MarketData.MarketAPI(flag=flag)
        self.tracker = TradeTracker()

        # 取得帳戶餘額並記錄相關資訊
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
        # 初始化核心策略 (SmaCore)，參數由外部傳入
        self.strategy = SmaCore(short_period, long_period)
        self.position = None  # 初始無部位

    def place_and_track_market_order(self, side, size, timeout=10):
        """
        下市價單並等待訂單完全成交或取消。

        參數:
            side (str): 交易方向 ("buy" 或 "sell")。
            size (float): 下單數量，單位依 tgtCcy 參數而定（此處為基礎幣）。
            timeout (int): 等待訂單成交的超時秒數。

        回傳:
            dict: 成交結果，包含成交價格與數量；若下單或成交失敗則回傳 None。
        """
        # 呼叫 API 下單，並指定 tgtCcy="base_ccy" 表示數量以基礎幣計算
        order = self.tradeAPI.place_order(
            instId=self.symbol,
            tdMode="cash",
            side=side,
            ordType="market",
            sz=str(size),
            tgtCcy="base_ccy",
        )

        # 檢查下單是否成功
        if order.get("code") != "0":
            self.log(f"❌ 下單失敗: {order}")
            return None

        order_id = order["data"][0]["ordId"]
        self.log(f"✅ 下單成功，ordId: {order_id}")

        # 輪詢等待訂單成交或取消
        final = self.wait_for_fill_or_cancel(order_id, timeout=timeout)
        if not final:
            self.log("❌ 訂單未成交，已取消")
            return None

        # 解析成交價格、數量與手續費
        price = float(final["fillPx"])
        amount = float(final["fillSz"])
        fee = abs(float(final["fee"]))
        fee_ccy = final.get("feeCcy", "?")  # 手續費幣別

        # 如果手續費幣別為 BTC，則換算成 USDT 等值，方便閱讀
        if fee_ccy.upper() == "BTC":
            fee_usdt = fee * price
            fee_display = f"{fee:.8f} BTC（≈ {fee_usdt:.2f} USDT）"
        else:
            fee_display = f"{fee:.6f} {fee_ccy}"

        # 記錄該筆交易
        self.tracker.record_trade(side, price, amount, fee)
        self.log(
            f"📌 成交：{side.upper()} {amount:.6f} @ {price:.2f}, 手續費: {fee_display}"
        )
        self.log(f"📊 累積盈虧：{self.tracker.get_profit():,.2f} USD")

        return {"price": price, "amount": amount}

    def wait_for_fill_or_cancel(self, order_id, timeout=5):
        """
        輪詢訂單狀態，等待訂單完全成交或超時後取消訂單。

        參數:
            order_id (str): 訂單識別碼。
            timeout (int): 等待超時秒數。

        回傳:
            dict: 完成訂單的資料 (若成交成功)；若失敗則回傳 None。
        """
        start = time.time()
        while time.time() - start < timeout:
            try:
                order = self.tradeAPI.get_order(instId=self.symbol, ordId=order_id)
                data = order.get("data", [])
                # 檢查是否完全成交
                if data and data[0].get("state") == "filled":
                    return data[0]
                # 若部分成交則記錄提示訊息
                elif data and data[0].get("state") == "partially_filled":
                    self.log("⚠️ 訂單部分成交中...")
            except Exception as e:
                self.log(f"⚠️ 查詢訂單失敗: {e}")
            time.sleep(1)

        # 超時後嘗試取消訂單
        try:
            self.tradeAPI.cancel_order(instId=self.symbol, ordId=order_id)
            self.log(f"🛑 超時未成交，已取消訂單 {order_id}")
        except Exception as e:
            self.log(f"❌ 取消訂單失敗: {e}")
        return None

    def log(self, message, dt=None, to_print=True):
        """
        統一的 log 輸出函數，將訊息同時印出並寫入檔案。

        參數:
            message (str): 要記錄的訊息。
            dt (datetime, optional): 訊息時間，預設為當前時間。
            to_print (bool): 是否同時印出訊息至 console，預設 True。
        """
        dt = dt or datetime.datetime.now()
        full_message = f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {message}"
        if to_print:
            print(full_message)
        logger.info(full_message)

    def get_balance_for_pair(self, pair):
        """
        查詢指定交易對的帳戶餘額資訊。

        參數:
            pair (str): 交易對字串，例如 "BTC-USDT"。

        回傳:
            dict: 包含基礎幣與報價幣的數量、以 USD 換算的價值，以及總 USD 價值；若失敗回傳 None。
        """
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
        """
        取得指定交易對的簡易行情資訊。

        參數:
            api: 市場資料 API 物件。
            inst_id (str): 交易對字串，例如 "BTC-USDT"。

        回傳:
            dict: 包含 timestamp、instType、instId、last（最新價）及 lastSz（成交量）的行情資料；若失敗回傳 None。
        """
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
        """
        主迴圈：
          - 定期取得最新行情並記錄。
          - 將市價傳入核心 SMA 模組以取得交易訊號，並根據訊號進行買賣操作。
          - 捕捉 KeyboardInterrupt 後若有持倉則強制平倉，最後統計並列印交易結果摘要。
        """
        self.log("\n\n" + "*" * 50)
        self.log("啟動 OKX 沙盒實盤模擬交易程序")
        self.log(f"交易幣對: {self.symbol}")
        balance_info = self.get_balance_for_pair(self.symbol)
        if balance_info:
            self.log("目前手上幣對數量及其市值:")
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
            init_total_usd = 0

        self.buy_count = 0
        self.sell_count = 0

        try:
            self.log("\n\n" + "*" * 50)
            self.log("策略開始")
            while True:
                # 取得行情
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

                # 更新核心策略，取得交易訊號 ("buy", "sell" 或 None)
                signal = self.strategy.update(current_price)
                if signal == "buy":
                    if self.position is None:
                        self.log("核心策略發出買入訊號")
                        # 根據設定的 USDT 金額計算下單數量
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
            # 捕捉到中斷訊號後開始結束流程
            self.end_time = datetime.datetime.now()
            self.log("\n\n" + "*" * 50)
            self.log("收到 KeyboardInterrupt，程式準備結束")

            # 結束前若仍有持倉則嘗試強制平倉
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

            # 取得結束時帳戶餘額並計算盈虧
            balance_info = self.get_balance_for_pair(self.symbol)
            if balance_info:
                self.log("目前手上幣對數量及其市值:")
                self.log(
                    f"{balance_info['base_currency']}: {balance_info['base_amount']:,.6f} {balance_info['base_currency']}（價值 ${balance_info['base_eqUsd']:,.0f} USD）"
                )
                self.log(
                    f"{balance_info['quote_currency']}: {balance_info['quote_amount']:,.6f} {balance_info['quote_currency']}（價值 ${balance_info['quote_eqUsd']:,.0f} USD）"
                )
                self.log(f"BTC+USDT 總價值 ${balance_info['total_usd_value']:,.0f} USD")
                final_total_usd = balance_info["total_usd_value"]
            else:
                self.log("無法獲取帳戶餘額")
                final_total_usd = 0

            profit = final_total_usd - init_total_usd
            profit_rate = (profit / init_total_usd) * 100 if init_total_usd != 0 else 0

            self.log(
                f"📊 已實現損益（策略本身盈虧）: {self.tracker.get_profit():,.2f} USD"
            )
            self.log(f"📊 賬戶總資產變動: {final_total_usd - init_total_usd:,.2f} USD")

            summary = {
                "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "initial_capital": init_total_usd,
                "final_value": final_total_usd,
                "profit": profit,
                "profit_rate": profit_rate,
                "buy_count": self.buy_count,
                "sell_count": self.sell_count,
                "total_fee_usd": self.tracker.get_total_fee(),
                "buy_usdt": self.buy_usdt,
                "short_period": self.strategy.short_period,
                "long_period": self.strategy.long_period,
            }
            self.log("交易結束，統計結果如下：")
            for key, value in summary.items():
                self.log(f"{key}: {value}")
            return


if __name__ == "__main__":
    # 設定輪詢間隔與每次買入金額
    poll_interval = 1  # 輪詢間隔（秒）
    buy_usdt = 100  # 每次買入金額（USDT）
    sandbox = LiveSandboxTrading(
        symbol="BTC-USDT",
        poll_interval=poll_interval,
        buy_usdt=buy_usdt,
        short_period=2,  # 短期 SMA 參數
        long_period=4,  # 長期 SMA 參數
    )
    sandbox.run()
