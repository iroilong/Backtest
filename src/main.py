from utils.data_loader import DataLoader
from utils.kline_plotter import plot_candlestick_chart
from backtest_engines.backtrader_engine import BacktraderEngine
from strategies.bearish_reversal_strategy import (
    run_bearish_reversal_backtest,
    run_bearish_reversal_backtest_multi,
)


# 資料庫連線設定
db_config = {
    "host": "iroilong.synology.me",
    "port": 33067,
    "user": "crypto",
    "password": "Crypto888#",
    "database": "crypto_db",
}

# ccxt 參數（不包含日期）
ccxt_config = {"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "15m"}

# 本地資料夾設定
local_db_dir = "./data/sqlite_db"
csv_dir = "./data/csv_data"

# 初始化 DataLoader，並傳入 db_config, local_db_dir, csv_dir 與 ccxt_config
data_loader = DataLoader(
    ccxt_config=ccxt_config,
    db_config=db_config,
    local_db_dir=local_db_dir,
    csv_dir=csv_dir,
)

# 產生統一的表格名稱 (例如: binance_BTC_USDT_1m)
table_name = DataLoader.generate_table_name(
    ccxt_config["exchange_id"], ccxt_config["symbol"], ccxt_config["timeframe"]
)
print(f"使用的資料表名稱: {table_name}")


# 載入指定時間區段的資料
df = data_loader.load_data(
    table_name,
    destination="ccxt",
    start_time="2025-03-01 00:00:00",
    end_time="2025-03-20 15:59:59",
)
# print(df.head())

# (若需要繪圖，取消以下註解)
# plot_candlestick_chart(df_data, title=f"{symbol} {timeframe} Candlestick Chart")


engine = BacktraderEngine()

# 呼叫 bearish_reversal 策略單次回測
result = run_bearish_reversal_backtest(
    engine,
    df,  # 載入的資料
    init_cash=10000,
    percent=90,
    consecutive=3,  # bearish_reversal 策略所需參數：連續陰線門檻
    tp_pct=3,  # 止盈百分比
    sl_pct=-1,  # 止損百分比
    plot=True,
)
print("回測結果：", result)

# 多組參數回測示例 (使用 bearish_reversal 策略)
# results_df = run_bearish_reversal_backtest_multi(
#     engine,
#     df,
#     init_cashes=[10000],
#     percents=[90],
#     consecutives=[3, 4],
#     tp_pct_list=[1, 3, 5],
#     sl_pct_list=[-1, -3],
# )
# print("多組回測結果：")
# print(results_df.sort_values(by="profit_rate"))
