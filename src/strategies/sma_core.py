"""
程式概要說明:
    此模組定義核心 SMA 策略邏輯，負責根據傳入的價格序列計算短期 SMA 與長期 SMA，
    並根據兩者的關係產生買入或賣出訊號。訊號僅在與前一次不同時回傳，避免重複觸發。
"""


class SmaCore:
    def __init__(self, short_period=5, long_period=20):
        # 短期與長期 SMA 的計算週期設定
        self.short_period = short_period
        self.long_period = long_period
        self.prices = []  # 用於儲存依序傳入的價格資料
        self.last_signal = None  # 紀錄上一次的交易訊號

    def update(self, price):
        """
        傳入最新的價格，更新價格序列並計算短期與長期 SMA。
        當短期 SMA 大於長期 SMA 時產生 "buy" 訊號，
        當短期 SMA 小於長期 SMA 時產生 "sell" 訊號，
        僅當訊號變化時回傳新訊號，否則回傳 None。

        參數:
            price (float): 最新的價格

        回傳:
            str 或 None: "buy"、"sell" 或 None（若無訊號變化）
        """
        self.prices.append(price)

        # 若目前價格數量不足以計算長期 SMA，則無法產生訊號
        if len(self.prices) < self.long_period:
            return None

        # 計算短期 SMA 與長期 SMA
        short_sma = sum(self.prices[-self.short_period :]) / self.short_period
        long_sma = sum(self.prices[-self.long_period :]) / self.long_period

        signal = None
        # 若短期 SMA 大於長期 SMA，設定訊號為 "buy"；反之設定為 "sell"
        if short_sma > long_sma:
            signal = "buy"
        elif short_sma < long_sma:
            signal = "sell"

        # 只有當訊號與上一次不同時才回傳，以避免重複觸發
        if signal != self.last_signal:
            self.last_signal = signal
            return signal

        return None
