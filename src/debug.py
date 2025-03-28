import os
import sqlite3
import pandas as pd
import backtrader as bt
import time  # 用於計時


# ---------------------------------------------
# 固定金額 Sizer：每次下單金額固定為初始資金的固定百分比，
# 若剩餘資金不足則以剩餘資金計算下單數量
class FixedAmountSizer(bt.Sizer):
    params = (("fixed_percent", 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        initial_cash = self.broker.startingcash
        order_value = initial_cash * self.p.fixed_percent / 100.0
        if cash < order_value:
            order_value = cash
        size = order_value / data.close[0]
        return size


# ---------------------------------------------
# Commission 設定：直接回傳 0
class MakerTakerCommission(bt.CommInfoBase):
    def getcommission(self, size, price):
        return 0


# ---------------------------------------------
# 資料載入函數 (假設資料表名稱為 kline)
def load_data(db_path: str):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"資料庫不存在：{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM kline ORDER BY datetime ASC", conn)
    finally:
        conn.close()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    if "openinterest" not in df.columns:
        df["openinterest"] = 0
    return df


# ---------------------------------------------
# 策略：連續 N 根陰線達成後等待第一根陽線進場，下市價買入固定金額的 BTC，
# 買入成交後，根據買入價格計算止盈（買入價*(1+tp_pct/100)）與止損（買入價*(1+sl_pct/100)）價格，
# 每根 Bar 檢查是否有任何已開倉交易達到出場條件，若當前 Bar 的最高價 >= 止盈價格，
# 或最低價 <= 止損價格，則以市價平倉賣出，並在成交日誌中標明是止盈還是止損。
# 進場部分：只有當沒有持倉時才評估進場條件，出場後才會再次進場。
class ConsecutiveBearishBuyMarketStrategy(bt.Strategy):
    params = (
        ("consecutive", 3),  # 連續陰線數
        ("take_profit_pct", 3),  # 止盈百分比，例：3代表+3%
        ("stop_loss_pct", -2),  # 止損百分比，例：-2代表-2%
    )

    def __init__(self):
        self.streak_count = 0  # 累計符合條件的陰線數
        self.waiting = False  # 是否進入等待買單狀態
        # 用來記錄每筆買入交易，格式：{'entry_price': ..., 'size': ...}
        self.open_trades = []

    def next(self):
        # 先檢查所有已開倉交易是否觸及出場條件（只在有持倉時才有效）
        if self.position:
            trades_to_exit = []
            for i, trade in enumerate(self.open_trades):
                target_profit = trade["entry_price"] * (
                    1 + self.p.take_profit_pct / 100.0
                )
                target_stop = trade["entry_price"] * (1 + self.p.stop_loss_pct / 100.0)
                exit_triggered = False
                exit_reason = ""
                if self.data.high[0] >= target_profit:
                    self.log(
                        f"止盈條件達成：當前Bar High {self.data.high[0]:.2f} >= 目標止盈 {target_profit:.2f}"
                    )
                    exit_triggered = True
                    exit_reason = "止盈"
                elif self.data.low[0] <= target_stop:
                    self.log(
                        f"止損條件達成：當前Bar Low {self.data.low[0]:.2f} <= 目標止損 {target_stop:.2f}"
                    )
                    exit_triggered = True
                    exit_reason = "止損"
                if exit_triggered:
                    # 以市價下單平倉，並在訂單 info 中傳入 exit_reason
                    self.sell(
                        exectype=bt.Order.Market,
                        size=trade["size"],
                        info={"exit_reason": exit_reason},
                    )
                    trades_to_exit.append(i)
            for i in sorted(trades_to_exit, reverse=True):
                del self.open_trades[i]
            # 如果持有部位，則不再評估進場條件
            return

        # 當無持倉時，評估進場條件
        if not self.waiting:
            if self.data.close[0] < self.data.open[0]:
                if self.streak_count == 0:
                    self.streak_count = 1
                else:
                    if self.data.low[0] < self.data.low[-1]:
                        self.streak_count += 1
                    else:
                        self.streak_count = 1
            else:
                self.streak_count = 0

            if self.streak_count >= self.p.consecutive:
                self.waiting = True
                self.log(f"連續 {self.streak_count} 根陰線達成，等待第一根陽線進場")
                dt = self.data.datetime.datetime(0)
                o = self.data.open[0]
                h = self.data.high[0]
                l = self.data.low[0]
                c = self.data.close[0]
                v = self.data.volume[0] if hasattr(self.data, "volume") else "N/A"
                print(
                    f"詳細資料: Time: {dt.strftime('%Y-%m-%d %H:%M:%S')}, "
                    f"O={o:.2f}, H={h:.2f}, L={l:.2f}, C={c:.2f}, V={v}"
                )
        else:
            # 當等待狀態下，遇到第一根陽線（收盤 > 開盤）則送出市價買入單
            if self.data.close[0] > self.data.open[0]:
                self.log("第一根陽線出現，送出市價買入單")
                order = self.buy(exectype=bt.Order.Market)
                self.waiting = False
                self.streak_count = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                entry_price = order.executed.price
                size = order.executed.size
                # 記錄該筆交易
                self.open_trades.append({"entry_price": entry_price, "size": size})
                remaining_cash = self.broker.getcash()
                coin_qty = self.getposition(self.data).size
                target = entry_price * (1 + self.p.take_profit_pct / 100.0)
                stop = entry_price * (1 + self.p.stop_loss_pct / 100.0)
                self.log(
                    f"買入成交：價格={entry_price:.2f}, 數量={size:.5f} BTC, 剩餘資金={remaining_cash:.2f} USDT, "
                    f"持倉量={coin_qty:.5f} BTC. 目標止盈價={target:.2f}, 目標止損價={stop:.2f}"
                )
            elif order.issell():
                sell_price = order.executed.price
                size = order.executed.size
                remaining_cash = self.broker.getcash()
                coin_qty = self.getposition(self.data).size
                exit_reason = order.info.get("exit_reason", "未知")
                self.log(
                    f"賣出成交 ({exit_reason})：價格={sell_price:.2f}, 數量={size:.5f} BTC, 剩餘資金={remaining_cash:.2f} USDT, "
                    f"持倉量={coin_qty:.5f} BTC."
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("訂單取消/保證金不足/拒絕")

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {txt}")


# ---------------------------------------------
# 單次回測函數：percent 參數代表每次下單使用初始資金的固定百分比（固定金額）
def run_backtest(
    init_cash,
    percent,
    consecutive,
    backtest_start,
    backtest_end,
    db_path,
    plot=True,
    tp_pct=3,
    sl_pct=-2,
):
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(init_cash)
    cerebro.addsizer(FixedAmountSizer, fixed_percent=percent)
    comminfo = MakerTakerCommission()
    cerebro.broker.addcommissioninfo(comminfo)

    df = load_data(db_path)
    df = df.loc[backtest_start:backtest_end]
    if df.empty:
        raise ValueError("指定回測區間內無資料")
    data = bt.feeds.PandasData(dataname=df.copy())
    cerebro.adddata(data)

    cerebro.addstrategy(
        ConsecutiveBearishBuyMarketStrategy,
        consecutive=consecutive,
        take_profit_pct=tp_pct,
        stop_loss_pct=sl_pct,
    )

    print(
        f"Running backtest: init_cash={init_cash}, percent={percent}, consecutive={consecutive}, tp_pct={tp_pct}, sl_pct={sl_pct}"
    )
    start_time = time.time()
    cerebro.run()
    elapsed = time.time() - start_time
    print(f"單次回測耗時: {elapsed:.2f} 秒")

    final_cash = cerebro.broker.getvalue()
    profit = final_cash - init_cash
    profit_rate = profit / init_cash * 100.0
    print(
        f"Final Cash: {final_cash:.2f}, Profit: {profit:.2f}, Profit Rate: {profit_rate:.2f}%"
    )

    if plot:
        cerebro.plot()

    result = {
        "backtest_start": backtest_start.strftime("%Y-%m-%d"),
        "backtest_end": backtest_end.strftime("%Y-%m-%d"),
        "init_cash": init_cash,
        "percent": percent,
        "consecutive": consecutive,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "final_cash": final_cash,
        "profit": profit,
        "profit_rate": profit_rate,
        "elapsed": elapsed,
    }
    return result


# ---------------------------------------------
# 多組參數回測函數：計算所有組合回測的總耗時
def run_backtest_multi(
    init_cashes,
    percents,
    consecutives,
    tp_pct_list,
    sl_pct_list,
    backtest_start,
    backtest_end,
    db_path,
):
    import pandas as pd

    results = []
    total_start = time.time()
    for init_cash in init_cashes:
        for percent in percents:
            for consecutive in consecutives:
                for tp_pct in tp_pct_list:
                    for sl_pct in sl_pct_list:
                        print("=" * 50)
                        result = run_backtest(
                            init_cash,
                            percent,
                            consecutive,
                            backtest_start,
                            backtest_end,
                            db_path,
                            plot=False,
                            tp_pct=tp_pct,
                            sl_pct=sl_pct,
                        )
                        result.update({"tp_pct": tp_pct, "sl_pct": sl_pct})
                        results.append(result)
    total_elapsed = time.time() - total_start
    print(f"多組回測總耗時: {total_elapsed:.2f} 秒")
    return pd.DataFrame(results)


# ---------------------------------------------
if __name__ == "__main__":
    # 測試參數設定
    backtest_start = pd.to_datetime("2025-03-01")
    backtest_end = pd.to_datetime("2025-03-08 23:59:59")
    db_path = os.path.join("data", "binance_BTC_USDT_5m.sqlite")

    RUN_SINGLE = 1
    if RUN_SINGLE:
        # 資金 10000 USDT，每次下單固定 10%（即1000 USDT），連續陰線門檻 5 根，
        # 止盈設 +3%，止損設 -3%
        result = run_backtest(
            10000,
            20,
            2,
            backtest_start,
            backtest_end,
            db_path,
            plot=True,
            tp_pct=1,
            sl_pct=-2,
        )
        print(result)
    else:
        init_cashes = [10000]
        percents = [20]
        consecutives = [2, 3, 4, 5, 6, 7]
        tp_pct_list = [1, 2, 3, 4, 5]  # 止盈百分比選項
        sl_pct_list = [-1, -2, -3, -4, -5]  # 止損百分比選項
        results_df = run_backtest_multi(
            init_cashes,
            percents,
            consecutives,
            tp_pct_list,
            sl_pct_list,
            backtest_start,
            backtest_end,
            db_path,
        )
        print("\n多組回測結果:")
        results_df_sorted = results_df.sort_values(by="profit_rate")
        print(results_df_sorted)
        results_df_sorted.to_csv("result/backtest_multi_results.csv", index=False)
