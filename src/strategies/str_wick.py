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
# Commission 設定：根據成交價與成交量計算佣金，預設 taker 費率 0.04%，maker 0.02%
class MakerTakerCommission(bt.CommInfoBase):
    def getcommission(self, size, price):
        return 0  # 此處佣金計算將在 notify_order 裡處理


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
# 每根 Bar 檢查是否有已開倉交易觸及出場條件，
# 若當前 Bar 的最高價 >= 止盈價格，或最低價 <= 止損價格，則以市價平倉賣出，
# 並在成交日誌中標明出場原因。進場部分僅在無持倉時執行（一買一賣模式）。
class ConsecutiveBearishBuyMarketStrategy(bt.Strategy):
    params = (
        ("consecutive", 3),  # 連續陰線數
        ("take_profit_pct", 3),  # 止盈百分比，例如 3 表示 +3%
        ("stop_loss_pct", -2),  # 止損百分比，例如 -2 表示 -2%
    )

    def __init__(self):
        self.streak_count = 0  # 累計符合條件的陰線數
        self.waiting = False  # 是否進入等待買單狀態
        self.open_trades = (
            []
        )  # 記錄每筆買入交易，格式：{'entry_price': ..., 'size': ...}
        self.event_log = []  # 存放每次買賣成交事件的詳細資訊
        self.buy_count = 0
        self.sell_count = 0
        self.total_commission = 0.0

    def next(self):
        # 若有持倉，先檢查出場條件；有持倉時不評估進場條件
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
                    self.sell(
                        exectype=bt.Order.Market,
                        size=trade["size"],
                        info={"exit_reason": exit_reason},
                    )
                    trades_to_exit.append(i)
            for i in sorted(trades_to_exit, reverse=True):
                del self.open_trades[i]
            return

        # 無持倉時，評估進場條件（連續陰線）
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
            if self.data.close[0] > self.data.open[0]:
                self.log("第一根陽線出現，送出市價買入單")
                order = self.buy(exectype=bt.Order.Market)
                self.waiting = False
                self.streak_count = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            # Commission 計算
            trade_value = abs(order.executed.size * order.executed.price)
            commrate = 0.0004  # 預設 taker 費率
            if order.info.get("maker_or_taker", "taker") == "maker":
                commrate = 0.0002
            commission = trade_value * commrate
            order.executed.comm = commission
            self.total_commission += commission

            timestamp = self.data.datetime.datetime(0).strftime("%Y-%m-%d %H:%M:%S")
            if order.isbuy():
                self.buy_count += 1
                entry_price = order.executed.price
                size = order.executed.size
                self.open_trades.append({"entry_price": entry_price, "size": size})
                remaining_cash = self.broker.getcash()
                coin_qty = self.getposition(self.data).size
                target = entry_price * (1 + self.p.take_profit_pct / 100.0)
                stop = entry_price * (1 + self.p.stop_loss_pct / 100.0)
                log_msg = (
                    f"買入成交：價格={entry_price:.2f}, 數量={size:.5f} BTC, "
                    f"剩餘資金={remaining_cash:.2f} USDT, 持倉量={coin_qty:.5f} BTC, "
                    f"目標止盈價={target:.2f}, 目標止損價={stop:.2f}, 佣金={commission:.2f}"
                )
                self.log(log_msg)
                self.event_log.append(
                    {
                        "time": timestamp,
                        "event": "買入成交",
                        "price": entry_price,
                        "size": size,
                        "remaining_cash": remaining_cash,
                        "position": coin_qty,
                        "details": f"目標止盈價={target:.2f}, 目標止損價={stop:.2f}, 佣金={commission:.2f}",
                    }
                )
            elif order.issell():
                self.sell_count += 1
                sell_price = order.executed.price
                size = order.executed.size
                remaining_cash = self.broker.getcash()
                coin_qty = self.getposition(self.data).size
                exit_reason = order.info.get("exit_reason", "未知")
                log_msg = (
                    f"賣出成交 ({exit_reason})：價格={sell_price:.2f}, 數量={size:.5f} BTC, "
                    f"剩餘資金={remaining_cash:.2f} USDT, 持倉量={coin_qty:.5f} BTC, 佣金={commission:.2f}"
                )
                self.log(log_msg)
                self.event_log.append(
                    {
                        "time": timestamp,
                        "event": f"賣出成交 ({exit_reason})",
                        "price": sell_price,
                        "size": size,
                        "remaining_cash": remaining_cash,
                        "position": coin_qty,
                        "details": f"佣金={commission:.2f}",
                    }
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("訂單取消/保證金不足/拒絕")

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {txt}")

    def stop(self):
        self.log(
            f"策略結束：買入次數={self.buy_count}, 賣出次數={self.sell_count}, 總佣金={self.total_commission:.2f}"
        )


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
    strategies = cerebro.run()
    elapsed = time.time() - start_time
    print(f"單次回測耗時: {elapsed:.2f} 秒")

    strat = strategies[0]
    final_cash = cerebro.broker.getvalue()
    profit = final_cash - init_cash
    profit_rate = profit / init_cash * 100.0
    print(
        f"Final Cash: {final_cash:.2f}, Profit: {profit:.2f}, Profit Rate: {profit_rate:.2f}%"
    )

    # 製作摘要報告，將所有指定資訊存入一個 DataFrame
    summary = {
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
        "buy_count": strat.buy_count,
        "sell_count": strat.sell_count,
        "total_commission": strat.total_commission,
    }
    df_summary = pd.DataFrame([summary])
    df_events = pd.DataFrame(strat.event_log)

    # 將摘要與事件記錄合併寫入同一個 CSV 報告，摘要在上，事件在下
    results_dir = "results"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    report_path = os.path.join(results_dir, "backtest_single_result.csv")
    with open(report_path, "w", newline="") as f:
        f.write("==== 摘要 ====\n")
        df_summary.to_csv(f, index=False)
        f.write("\n==== 事件記錄 ====\n")
        df_events.to_csv(f, index=False)
    print(f"單次回測報告已存到 {report_path}")

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
        "buy_count": strat.buy_count,
        "sell_count": strat.sell_count,
        "total_commission": strat.total_commission,
    }
    return result


# ---------------------------------------------
# 多組參數回測函數：計算所有組合回測的總耗時，並記錄每筆測試的買賣次數與總佣金
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
    df_results = pd.DataFrame(results)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    results_filename = f"backtest_multi_result_{timestamp}.csv"
    df_results_sorted = df_results.sort_values(by="profit_rate", ascending=False)
    results_path = os.path.join("results", results_filename)
    df_results_sorted.to_csv(results_path, index=False)
    print(f"多組回測結果已存到 {results_path}")
    return df_results


# ---------------------------------------------
if __name__ == "__main__":
    # 測試參數設定
    backtest_start = pd.to_datetime("2025-03-01")
    backtest_end = pd.to_datetime("2025-03-13 23:59:59")
    db_path = os.path.join("data", "binance_BTC_USDT_5m.sqlite")

    SINGLE_1_MILTI_0 = 1
    if SINGLE_1_MILTI_0:
        # 單次回測測試：資金 10000 USDT，每次下單固定 10%（即1000 USDT），連續陰線門檻 5 根，
        # 止盈設 +3%，止損設 -3%
        result = run_backtest(
            10000,
            100,
            5,
            backtest_start,
            backtest_end,
            db_path,
            plot=True,
            tp_pct=3,
            sl_pct=-1,
        )
        print(result)
    else:
        init_cashes = [10000]
        percents = [100]
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
