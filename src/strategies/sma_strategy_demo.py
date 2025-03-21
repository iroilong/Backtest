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


# -----------------------
# 沙盒實盤交易類別
# -----------------------
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


class LiveSandboxTrading:
    """
    程式概要說明:
        利用 OKX 官方 API 在沙盒環境下進行實盤模擬交易：
          - 程式啟動時讀取帳戶餘額（USDT 與 BTC 換算成 USDT 加總），記錄初始總資產與開始時間。
          - 每隔 poll_interval 秒透過 MarketAPI.get_ticker() 取得最新行情（ticker 中的時間轉換為台灣時區）。
          - 將目前市價傳入核心 SMA 模組 (SmaCore) 以獲得交易訊號，當產生買/賣訊號時，
            分別利用 OrderAPI.create_order() 下市價單，並根據訂單 id 輪詢確認訂單狀態（直到 filled）。
          - 程式可使用 Ctrl+C 結束，結束前重新取得帳戶餘額並計算 profit（最終總資產 – 初始總資產），
            並列印出統計摘要（包括 start_time、end_time、initial_capital、final_value、profit、profit_rate、buy_count、sell_count、total_fee_usdt、buy_usdt、short_period 與 long_period）。
    """

    def __init__(
        self,
        symbol="BTC-USDT",
        poll_interval=60,
        buy_usdt=300,
        short_period=5,
        long_period=20,
    ):
        """
        初始化參數：
          poll_interval: 輪詢間隔秒數
          buy_usdt: 每次買入固定 USDT 金額
          short_period, long_period: 核心 SMA 週期參數
        """
        self.start_time = datetime.datetime.now()

        # OKX DEMO API 資訊
        self.api_key = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
        self.secret_key = "D5CBAFD3B4B13991EED0BB0669A73582"
        self.passphrase = "Okx7513#"
        # OKX 官方 API 常用的交易對格式為 "BTC-USDT"
        self.symbol = symbol

        # 建立 OKX API 物件（帳戶、訂單、市場）
        flag = "1"  # live trading: 0, demo trading: 1

        self.accountAPI = Account.AccountAPI(
            self.api_key, self.secret_key, self.passphrase, False, flag
        )
        self.tradeAPI = Trade.TradeAPI(
            self.api_key, self.secret_key, self.passphrase, False, flag
        )
        self.marketDataAPI = MarketData.MarketAPI(flag=flag)

        # 取得帳戶資訊並 log 出部分幣種餘額
        # 取得帳戶資訊並印出各幣種餘額
        self.log(f"帳戶資產如下:")
        try:
            balance_data = self.accountAPI.get_account_balance()
            # 檢查 API 回傳是否成功（code 為 "0" 表示成功）
            if balance_data.get("code") == "0":
                data = balance_data.get("data", [{}])[0]
                details = data.get("details", [])
                for asset in details:
                    ccy = asset.get("ccy", "N/A")
                    availBal = asset.get("availBal", "0")
                    eqUsd = asset.get("eqUsd", "0")
                    # 以格式 "幣種 = availBal (eqUsd USDT)" log 出來
                    self.log(f"{ccy} = {availBal} ({float(eqUsd):.0f} USD)")
                total_eq = data.get("totalEq", "0")
                self.log(f"帳戶總資產 = {float(total_eq):.0f} USD")
            else:
                self.log(f"取得帳戶資訊失敗: {balance_data}")
        except Exception as e:
            self.log(f"取得帳戶資訊失敗：{e}")

        self.poll_interval = poll_interval
        self.buy_usdt = buy_usdt

        # 初始化核心策略 (SmaCore)；短期、長期參數由外部傳入
        self.strategy = SmaCore(short_period, long_period)
        self.position = None  # 初始無部位

    def buy_market(self, usdt_amount):
        return self.place_and_track_market_order("buy", usdt_amount, mode="usdt")

    def sell_market(self, base_amount):
        return self.place_and_track_market_order("sell", base_amount, mode="base")

    def round_down(self, value, precision=5):
        factor = 10**precision
        return int(value * factor) / factor

    def get_latest_price(self):
        try:
            tick = self.marketDataAPI.get_ticker(instId=self.symbol)
            return float(tick["data"][0]["last"])
        except Exception as e:
            self.log(f"⚠️ 無法取得市價: {e}")
            return None

    def place_and_track_market_order(self, side, size, timeout=5, mode="usdt"):
        price = self.get_latest_price()
        if price is None:
            self.log("❌ 無法取得市價，下單取消")
            return None

        # ✨ 根據 mode 決定怎麼處理下單數量
        if mode == "usdt":
            amount = self.round_down(size / price, 5)
        elif mode == "base":
            amount = self.round_down(size, 5)
        else:
            self.log(f"❌ 未知下單模式: {mode}")
            return None

        if price * amount < 5:
            self.log(
                f"⚠️ 金額過小：{amount:.8f} × {price:.2f} = {price * amount:.2f}，低於 5 USDT，跳過下單"
            )
            return None

        self.log(f"下單: side = {side}, size = {amount:.8f}")

        order = self.tradeAPI.place_order(
            instId=self.symbol,
            tdMode="cash",
            side=side,
            ordType="market",
            sz=str(amount),
        )

        if order.get("code") != "0":
            self.log(f"❌ 下單失敗: {order}")
            return None

        order_id = order["data"][0]["ordId"]
        self.log(f"✅ 下單成功，ordId: {order_id}")

        # ⏳ 等待成交或取消
        final = self.wait_for_fill_or_cancel(order_id, timeout=timeout)
        if not final:
            self.log("❌ 訂單未成交，已取消")
            return None

        price = float(final["fillPx"])
        amount = float(final["fillSz"])
        fee = abs(float(final["fee"]))

        self.tracker.record_trade(side, price, amount, fee)
        self.log(
            f"📌 成交：{side.upper()} {amount:.6f} @ {price:.2f}, 手續費: {fee:.6f}"
        )
        self.log(f"📊 累積盈虧：{self.tracker.get_profit():,.2f} USD")

        return {"price": price, "amount": amount}

    def wait_for_fill_or_cancel(self, order_id, timeout=5):
        import time

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

    def round_down(self, value, precision=5):
        factor = 10**precision
        return int(value * factor) / factor

    def get_latest_price(self):
        try:
            tick = self.marketDataAPI.get_ticker(instId=self.symbol)
            return float(tick["data"][0]["last"])
        except Exception as e:
            self.log(f"⚠️ 無法取得市價: {e}")
            return None

    def log(self, message, dt=None, to_print=True):
        dt = dt or datetime.datetime.now()
        full_message = f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {message}"
        if to_print:
            print(full_message)
        logger.info(full_message)

    def get_balance_for_pair(self, pair):
        # 解析交易對，例如 "BTC-USDT" 變成 ["BTC", "USDT"]
        base_currency, quote_currency = pair.upper().split("-")

        # 取得帳戶餘額
        balance_data = self.accountAPI.get_account_balance()

        # API 請求成功（code == "0"）
        if balance_data.get("code") == "0":
            data = balance_data.get("data", [{}])[0]
            details = data.get("details", [])

            # 預設資產為 0
            base_amount = 0.0
            base_eqUsd = 0.0
            quote_amount = 0.0
            quote_eqUsd = 0.0

            # 遍歷帳戶所有資產，找到匹配的幣種
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

            # 計算該交易對的總美元價值
            total_usd_value = base_eqUsd + quote_eqUsd

            # 回傳結果
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
            print("取得 ticker 失敗")
            return None

        ticker = result["data"][0]
        return {
            "timestamp": ticker.get("ts"),  # 毫秒 timestamp
            "instType": ticker.get("instType"),
            "instId": ticker.get("instId"),
            "last": ticker.get("last"),
            "lastSz": ticker.get("lastSz"),
        }

    def wait_for_order(self, order_id, symbol, timeout=300):
        """
        輪詢訂單狀態，直到訂單狀態為 "filled" 或超時後返回訂單資訊。
        """
        start = time.time()
        while True:
            try:
                order = self.tradeAPI.get_order(instId=self.symbol, ordId=order_id)
                print(order)
                if order["data"][0]["state"] == "filled":
                    return order
            except Exception as e:
                self.log(f"查詢訂單 {order_id} 狀態錯誤：{e}")
            if time.time() - start > timeout:
                self.log(f"訂單 {order_id} 等待超時")
                return order
            time.sleep(1)

    def run(self):
        """
        主迴圈：每隔 poll_interval 秒取得最新行情（利用 MarketAPI.get_ticker），
        將 ticker 中的 UTC 時間轉換為台灣時區，然後傳入核心策略計算訊號，
        根據訊號進行買入或賣出，下單後透過 wait_for_order 等待訂單成交。
        捕捉 KeyboardInterrupt 優雅退出，退出前計算最終總資產並列印統計摘要。
        """
        self.log("啟動 OKX 沙盒實盤模擬交易程序")
        self.log(f"交易幣對: {self.symbol}")
        balance_info = self.get_balance_for_pair(self.symbol)
        if balance_info:
            self.log(
                f"{balance_info['base_currency']}: {balance_info['base_amount']:,.6f} {balance_info['base_currency']}（價值 ${balance_info['base_eqUsd']:,.0f} USD）"
            )
            self.log(
                f"{balance_info['quote_currency']}: {balance_info['quote_amount']:,.6f} {balance_info['quote_currency']}（價值 ${balance_info['quote_eqUsd']:,.0f} USD）"
            )
            init_base = balance_info["base_amount"]
            init_quote = balance_info["base_amount"]
            init_total_usd = balance_info["total_usd_value"]

        else:
            self.log("無法獲取帳戶餘額")

        self.tracker = TradeTracker()

        self.buy_count = 0
        self.sell_count = 0
        self.total_fee_usdt = 0
        try:
            while True:
                ticker = self.get_simple_ticker(self.marketDataAPI, "BTC-USDT")

                if ticker:
                    # 將 ticker 中的 datetime 轉換為台灣時區
                    timestamp = ticker["timestamp"]
                    taiwan_dt = tw_time = datetime.datetime.fromtimestamp(
                        int(timestamp) / 1000, tz=datetime.timezone.utc
                    ) + datetime.timedelta(hours=8)
                    volume = float(ticker["lastSz"])
                    current_price = float(ticker["last"])

                    self.log(
                        f"接收到行情：{tw_time.strftime('%Y-%m-%d %H:%M:%S')}, 市價: {current_price:.2f}, 成交量: {volume:.6f}"
                    )

                # 取得核心策略訊號
                signal = self.strategy.update(current_price)

                if signal == "buy":
                    if self.position is None:
                        self.log("核心策略發出買入訊號")
                        trade_result = self.buy_market(self.buy_usdt)
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
                        trade_result = self.sell_market(self.position["amount"])
                        if trade_result:
                            self.position = None
                            self.sell_count += 1
                    else:
                        self.log("無持倉，無法賣出")
                else:
                    self.log("無明確交易訊號")
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            self.end_time = datetime.datetime.now()
            self.log("收到 KeyboardInterrupt，程式準備結束")

            self.log(f"📊 實現盈虧總計：{self.tracker.get_profit():,.2f} USD")

            balance_info = self.get_balance_for_pair(self.symbol)
            if balance_info:
                self.log(
                    f"{balance_info['base_currency']}: {balance_info['base_amount']:,.6f} {balance_info['base_currency']}（價值 ${balance_info['base_eqUsd']:,.0f} USD）"
                )
                self.log(
                    f"{balance_info['quote_currency']}: {balance_info['quote_amount']:,.6f} {balance_info['quote_currency']}（價值 ${balance_info['quote_eqUsd']:,.0f} USD）"
                )
                final_base = balance_info["base_amount"]
                final_quote = balance_info["base_amount"]
                final_total_usd = balance_info["total_usd_value"]
            else:
                self.log("無法獲取帳戶餘額")

            profit = init_total_usd - final_total_usd
            profit_rate = (profit / init_total_usd) * 100 if init_total_usd != 0 else 0
            summary = {
                "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": self.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "initial_capital": init_total_usd,
                "final_value": final_total_usd,
                "profit": profit,
                "profit_rate": profit_rate,
                "buy_count": self.buy_count,
                "sell_count": self.sell_count,
                "total_fee_usdt": self.total_fee_usdt,
                "buy_usdt": self.buy_usdt,
                "short_period": self.strategy.short_period,
                "long_period": self.strategy.long_period,
            }
            self.log("交易結束，統計結果如下：")
            for key, value in summary.items():
                self.log(f"{key}: {value}")
            return


# -----------------------
# 主程式進入點
# -----------------------
if __name__ == "__main__":
    poll_interval = 1  # 例如 60 秒代表 1 分鐘行情更新
    buy_usdt = 3000  # 每次買入使用 300 USDT
    sandbox = LiveSandboxTrading(
        symbol="BTC-USDT",
        poll_interval=poll_interval,
        buy_usdt=buy_usdt,
        short_period=5,
        long_period=7,
    )
    sandbox.run()
