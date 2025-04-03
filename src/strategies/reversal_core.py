#!/usr/bin/env python3
"""
程式概要說明:
    此模組定義核心 Reversal 策略邏輯，
    策略流程為累計連續陰線（收盤價低於開盤價），
    當達到設定門檻後進入觸發狀態，
    並等待第一根陽線 (收盤價高於開盤價) 出現，即以市價單買入，
    之後根據成交價計算止盈與止損價格，
    在持倉期間，每根 K 線檢查是否達到止盈或止損目標，若達到則平倉，並重置狀態。
"""


class ReversalCore:
    def __init__(self, consecutive_bear_threshold, take_profit_pct, stop_loss_pct):
        """
        初始化 Reversal 策略核心。

        參數:
            consecutive_bear_threshold (int): 連續陰線門檻 (例如 3)
            take_profit_pct (float): 止盈百分比 (正數，例如 3 代表 +3%)
            stop_loss_pct (float): 止損百分比 (負數，例如 -2 代表 -2%)
        """
        # 儲存策略參數
        self.consecutive_bear_threshold = consecutive_bear_threshold
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct

        # 策略狀態管理
        self.bear_count = 0  # 累計連續陰線數量
        self.triggered = False  # 是否進入觸發狀態 (等待下一根陽線)
        self.in_position = False  # 是否已進入持倉狀態
        self.buy_price = None  # 紀錄進場買入價格
        self.take_profit_price = None  # 根據 buy_price 計算的止盈價
        self.stop_loss_price = None  # 根據 buy_price 計算的止損價
        self.last_signal = None  # 紀錄上一次訊號 (避免重複回傳)

    def update(self, candle):
        """
        傳入新的 K 線資料並更新策略狀態，根據策略邏輯回傳 "buy" 或 "sell" 訊號。

        參數:
            candle (dict): 一根 K 線資料，需包含以下鍵值:
                - "open": 開盤價
                - "high": 最高價
                - "low":  最低價
                - "close": 收盤價

        回傳:
            str 或 None: "buy"、"sell" 或 None（若無訊號變化）
        """
        open_price = candle["open"]
        high_price = candle["high"]
        low_price = candle["low"]
        close_price = candle["close"]

        # 尚未持倉時，檢查是否符合買入條件
        if not self.in_position:
            # 若尚未進入觸發狀態，累計陰線
            if not self.triggered:
                if close_price < open_price:
                    self.bear_count += 1
                else:
                    self.bear_count = 0

                # 達到連續陰線門檻時，進入觸發狀態
                if self.bear_count >= self.consecutive_bear_threshold:
                    self.triggered = True
            else:
                # 已進入觸發狀態，等待第一根陽線
                if close_price > open_price:
                    # 市價買入
                    self.in_position = True
                    self.triggered = False
                    self.bear_count = 0
                    self.buy_price = close_price

                    # 計算止盈、止損價
                    self.take_profit_price = self.buy_price * (
                        1 + self.take_profit_pct / 100.0
                    )
                    self.stop_loss_price = self.buy_price * (
                        1 + self.stop_loss_pct / 100.0
                    )

                    # 回傳買入訊號 (若與上次訊號不同)
                    if self.last_signal != "buy":
                        self.last_signal = "buy"
                        return "buy"
        else:
            # 已持倉，檢查是否達到止盈或止損
            if (
                high_price >= self.take_profit_price
                or low_price <= self.stop_loss_price
            ):
                # 達到止盈或止損，平倉
                self.in_position = False
                self.buy_price = None
                self.take_profit_price = None
                self.stop_loss_price = None
                self.bear_count = 0
                self.triggered = False

                # 回傳賣出訊號 (若與上次訊號不同)
                if self.last_signal != "sell":
                    self.last_signal = "sell"
                    return "sell"

        # 若沒有新的訊號，回傳 None
        return None


if __name__ == "__main__":
    # 測試 Reversal 策略的範例
    strategy = ReversalCore(
        consecutive_bear_threshold=3, take_profit_pct=3, stop_loss_pct=-2
    )

    # 模擬一系列 K 線資料
    test_candles = [
        {"open": 100, "high": 100, "low": 99, "close": 99},  # 陰線 1
        {"open": 99, "high": 99, "low": 98, "close": 98},  # 陰線 2
        {
            "open": 98,
            "high": 98,
            "low": 97,
            "close": 97,
        },  # 陰線 3 -> 達到門檻，進入觸發狀態
        {"open": 97, "high": 98, "low": 97, "close": 98},  # 陽線 -> 觸發買入訊號
        {"open": 98, "high": 101, "low": 98, "close": 100},  # 持倉中，未達止盈或止損
        {"open": 100, "high": 102, "low": 97, "close": 97},  # 觸發止損 -> 產生賣出訊號
    ]

    for i, candle in enumerate(test_candles, start=1):
        signal = strategy.update(candle)
        if signal:
            print(f"Candle {i}: Signal = {signal}")
        else:
            print(f"Candle {i}: No signal")
