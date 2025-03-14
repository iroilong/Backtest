from utils.data_loader import DataLoader
from utils.kline_plotter import plot_candlestick_chart
from backtest_engines.backtrader_engine import BacktraderEngine
from strategies.sma_strategy import (
    run_sma_backtest,
    run_sma_backtest_multi,
)


# 設定 NAS DB 連線資訊
db_config = {
    "host": "iroilong.synology.me",
    "port": 33067,
    "user": "crypto",
    "password": "Crypto888#",
    "database": "crypto_db",
}

# 設定本地 SQLite 與 CSV 儲存目錄
local_db_dir = "./sqlite_db"
csv_dir = "./csv_data"

# ccxt 下載參數
exchange_id = "binance"
symbol = "BTC/USDT"
timeframe = "5m"
start_date = "2025-03-01"
end_date = "2025-03-12"

# 產生統一的表格名稱
table_name = DataLoader.generate_table_name(exchange_id, symbol, timeframe)
print(f"使用的資料表名稱: {table_name}")

# 初始化 DataLoader
data_loader = DataLoader(
    db_config=db_config, local_db_dir=local_db_dir, csv_dir=csv_dir
)

# 載入指定時間區段的資料
start_time = "2025-03-03 00:00:00"
end_time = "2025-03-05 23:59:59"
df_data = data_loader.load_data(
    table_name, destination="nas", start_time=start_time, end_time=end_time
)
print(df_data.head())

# (若需要繪圖，取消以下註解)
# plot_candlestick_chart(df_data, title=f"{symbol} {timeframe} Candlestick Chart")


engine = BacktraderEngine()
# result = run_sma_backtest(
#     engine,
#     df_data,  # 載入的資料
#     init_cash=10000,
#     percent=50,
#     short_period=5,
#     long_period=20,
#     plot=True,
# )
# print("回測結果：", result)


# 多組參數回測示例
results_df = run_sma_backtest_multi(engine, df_data, [10000], [100], [5, 10], [20, 30])
print("多組回測結果：")
print(results_df)
