# sma_core.py


class SmaCore:
    def __init__(self, short_period=5, long_period=20):
        self.short_period = short_period
        self.long_period = long_period
        self.prices = []  # 儲存價格資料
        self.last_signal = None  # 紀錄上一次的信號

    def update(self, price):
        """
        傳入最新的價格，計算 SMA 並判斷是否產生新的交易信號。
        回傳:
            "buy" 或 "sell" 或 None（無變化）
        """
        self.prices.append(price)

        # 尚未足夠數據計算 long SMA
        if len(self.prices) < self.long_period:
            return None

        short_sma = sum(self.prices[-self.short_period :]) / self.short_period
        long_sma = sum(self.prices[-self.long_period :]) / self.long_period

        signal = None
        # 若短期 SMA 大於長期 SMA，產生買入訊號；反之產生賣出訊號
        if short_sma > long_sma:
            signal = "buy"
        elif short_sma < long_sma:
            signal = "sell"

        # 僅當信號改變時才回傳新信號
        if signal != self.last_signal:
            self.last_signal = signal
            return signal

        return None
