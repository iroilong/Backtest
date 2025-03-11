import os
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt


def load_data(db_path: str):
    """
    從 SQLite 資料庫讀取 kline 資料表，依據 datetime 排序，
    並轉換 datetime 欄位為 pandas datetime 物件。
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"資料庫不存在：{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM kline ORDER BY datetime ASC", conn)
    finally:
        conn.close()
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def simple_buy_and_hold_backtest(df: pd.DataFrame):
    """
    簡單的買進持有策略：
      - 以初始資金 $100 在第一筆資料的收盤價買進，
      - 持有至最後一筆資料的收盤價賣出，
      - 計算最終資產、獲利與獲利率，
      - 並產生資產曲線 (equity curve)。
    """
    if df.empty:
        return None
    initial_capital = 100.0
    buy_price = df.iloc[0]["close"]
    final_price = df.iloc[-1]["close"]
    # 買入股數（或幣數）
    shares = initial_capital / buy_price
    final_value = shares * final_price
    profit = final_value - initial_capital
    profit_ratio = final_value / initial_capital

    # 計算資產曲線：每筆資料的 portfolio value
    df["equity"] = shares * df["close"]

    return profit, profit_ratio, df


def plot_equity_curve(df: pd.DataFrame):
    """
    繪製資產曲線圖
    """
    plt.figure(figsize=(10, 6))
    plt.plot(df["datetime"], df["equity"], label="Equity Curve")
    plt.xlabel("Date")
    plt.ylabel("Portfolio Value")
    plt.title("Buy and Hold Equity Curve")
    plt.legend()
    plt.grid(True)
    plt.show()


def main():
    # 這裡假設資料庫檔名為 binance_BTC_USDT_1d.sqlite，請根據實際情況修改路徑
    db_path = os.path.join("data", "binance_BTC_USDT_1d.sqlite")

    # 讀取歷史資料
    df = load_data(db_path)

    # 執行買進持有回測
    result = simple_buy_and_hold_backtest(df)
    if result is None:
        print("無資料進行回測")
        return
    profit, profit_ratio, df_equity = result

    print("買進持有策略回測結果：")
    print(f"初始資金: $100")
    print(f"獲利: ${profit:.2f}")
    print(f"最終資產是初始資金的 {profit_ratio:.2f} 倍")

    # 繪製資產曲線圖
    plot_equity_curve(df_equity)


if __name__ == "__main__":
    main()
