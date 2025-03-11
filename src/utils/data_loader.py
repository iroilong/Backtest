from dataclasses import dataclass
import ccxt
import datetime
import time
import os
import sqlite3
import pandas as pd


# ------------------ Dataclass 定義 ------------------
@dataclass
class OHLCVIntervalParams:
    """
    高階設定參數
    Attributes:
        exchange_id: 交易所 ID (例如 "binance")
        symbol: 交易標的 (例如 "BTC/USDT")
        timeframe: 時間框架 (例如 "1d", "15m", "1m")
        start_date: 起始日期 (格式 "YYYY-MM-DD") -- update_exchange_data 使用
        end_date: 結束日期 (格式 "YYYY-MM-DD") -- update_exchange_data 使用
    """

    exchange_id: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str


@dataclass
class OHLCVFetchParams:
    """
    用於 fetch_ohlcv_interval 的低階參數
    Attributes:
        exchange: ccxt 交易所物件
        symbol: 交易標的
        timeframe: 時間框架
        since: 起始 timestamp (毫秒)
        end_timestamp: 結束 timestamp (毫秒)
    """

    exchange: ccxt.Exchange
    symbol: str
    timeframe: str
    since: int
    end_timestamp: int


# ------------------ 輔助函數 ------------------
def timeframe_to_millis(timeframe: str) -> int:
    """
    將 timeframe 轉換成毫秒數，例如:
      - "1m" -> 60000
      - "15m" -> 900000
      - "1d" -> 86400000
    """
    unit = timeframe[-1]
    number = int(timeframe[:-1])
    if unit == "m":
        return number * 60000
    elif unit == "h":
        return number * 3600000
    elif unit == "d":
        return number * 86400000
    else:
        raise ValueError("不支援的時間框架")


def get_db_interval(db_path: str):
    """
    檢查 DB 是否存在並回傳資料中的最早與最晚時間（以毫秒表示）。
    若 DB 不存在或無資料，則回傳 (None, None)
    """
    if not os.path.exists(db_path):
        return None, None
    conn = sqlite3.connect(db_path)
    try:
        query = "SELECT MIN(datetime) as min_dt, MAX(datetime) as max_dt FROM kline"
        result = pd.read_sql_query(query, conn)
        if result["min_dt"][0] is None or result["max_dt"][0] is None:
            return None, None
        min_dt = datetime.datetime.strptime(result["min_dt"][0], "%Y-%m-%d %H:%M:%S")
        max_dt = datetime.datetime.strptime(result["max_dt"][0], "%Y-%m-%d %H:%M:%S")
        min_ts = int(min_dt.timestamp() * 1000)
        max_ts = int(max_dt.timestamp() * 1000)
        return min_ts, max_ts
    finally:
        conn.close()


def get_exchange_instance(exchange_id: str, rate_limit=True):
    """
    根據使用者輸入的交易所 ID，取得 ccxt 交易所物件
    """
    try:
        exchange_class = getattr(ccxt, exchange_id.lower())
    except AttributeError:
        raise ValueError(f"ccxt 不支援此交易所: {exchange_id}")
    return exchange_class({"enableRateLimit": rate_limit})


def get_db_path(params: OHLCVIntervalParams) -> str:
    """
    根據 params 中的交易所、標的與時間框架，產生 DB 檔名與路徑。
    例如: binance_BTC_USDT_1m.sqlite
    """
    symbol_db = params.symbol.replace("/", "_")
    db_filename = f"{params.exchange_id.lower()}_{symbol_db}_{params.timeframe}.sqlite"
    return os.path.join("data", db_filename)


# ------------------ 資料下載相關函數 ------------------
def fetch_ohlcv_interval(fetch_params: OHLCVFetchParams):
    """
    使用封裝在 OHLCVFetchParams 中的參數下載 OHLCV 資料，
    並以迴圈方式取得整個區間內所有資料。
    """
    period = timeframe_to_millis(fetch_params.timeframe)
    all_ohlcv = []
    current_since = fetch_params.since  # 使用區域變數，避免直接修改物件屬性
    while True:
        start_str = datetime.datetime.fromtimestamp(
            current_since / 1000, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"正在下載 {fetch_params.symbol} {fetch_params.timeframe} 資料，從 {start_str} 起 ..."
        )
        ohlcv = fetch_params.exchange.fetch_ohlcv(
            fetch_params.symbol,
            timeframe=fetch_params.timeframe,
            since=current_since,
            limit=1000,
        )
        if not ohlcv:
            break
        filtered = [
            candle for candle in ohlcv if candle[0] <= fetch_params.end_timestamp
        ]
        all_ohlcv.extend(filtered)
        last_ts = ohlcv[-1][0]
        if last_ts >= fetch_params.end_timestamp:
            break
        current_since = last_ts + period
        time.sleep(fetch_params.exchange.rateLimit / 1000)
    return all_ohlcv


def ohlcv_to_dataframe(ohlcv, symbol):
    """
    將 OHLCV 清單轉成 DataFrame，同時將 timestamp 轉為 "YYYY-MM-DD HH:MM:SS" 格式，
    並加入 symbol 欄位。
    """
    data = []
    for candle in ohlcv:
        ts, open_, high, low, close, volume = candle
        dt_str = datetime.datetime.fromtimestamp(
            ts / 1000, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")
        data.append(
            {
                "datetime": dt_str,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "symbol": symbol,
            }
        )
    return pd.DataFrame(data)


def store_to_sqlite(df, db_path):
    """
    將 DataFrame 存入 DB 的 kline 資料表。
    若資料表已存在則以 append 模式寫入，寫入後會刪除重複的 datetime 紀錄。
    """
    db_dir = os.path.dirname(db_path)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    with sqlite3.connect(db_path) as conn:
        df.to_sql("kline", conn, if_exists="append", index=False)
        conn.execute(
            """
            DELETE FROM kline
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM kline
                GROUP BY datetime
            )
        """
        )
    print(f"資料已成功存入 {db_path}")


# ------------------ 主要功能函數 ------------------
def update_exchange_data(params: OHLCVIntervalParams):
    """
    根據指定區間（使用 params.start_date 與 params.end_date），
    檢查 DB 中現有資料，僅下載缺少的區段，並更新到對應的 SQLite 資料庫。
    """
    exchange = get_exchange_instance(params.exchange_id)
    db_path = get_db_path(params)

    # 轉換日期字串成 datetime 物件，並設定起始 00:00:00 與結束 23:59:59
    start_dt = datetime.datetime.strptime(params.start_date, "%Y-%m-%d")
    end_dt = datetime.datetime.strptime(params.end_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    )
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    # 檢查現有 DB 中的資料區間
    db_min_ts, db_max_ts = get_db_interval(db_path)
    missing_intervals = []
    if db_min_ts is None and db_max_ts is None:
        missing_intervals.append((start_ts, end_ts))
    else:
        if start_ts < db_min_ts:
            missing_intervals.append(
                (start_ts, db_min_ts - timeframe_to_millis(params.timeframe))
            )
        if end_ts > db_max_ts:
            missing_intervals.append(
                (db_max_ts + timeframe_to_millis(params.timeframe), end_ts)
            )

    if not missing_intervals:
        print("指定區間內資料已完整，不需更新。")
    else:
        all_new_ohlcv = []
        for interval in missing_intervals:
            interval_start, interval_end = interval
            start_interval_str = datetime.datetime.fromtimestamp(
                interval_start / 1000, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
            end_interval_str = datetime.datetime.fromtimestamp(
                interval_end / 1000, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
            print(f"下載缺少區段：{start_interval_str} 到 {end_interval_str}")
            fetch_params = OHLCVFetchParams(
                exchange=exchange,
                symbol=params.symbol,
                timeframe=params.timeframe,
                since=interval_start,
                end_timestamp=interval_end,
            )
            ohlcv = fetch_ohlcv_interval(fetch_params)
            if ohlcv:
                all_new_ohlcv.extend(ohlcv)
        if all_new_ohlcv:
            df_new = ohlcv_to_dataframe(all_new_ohlcv, params.symbol)
            store_to_sqlite(df_new, db_path)
        else:
            print("無新資料下載。")
    return db_path


def update_exchange_uptodate(params: OHLCVIntervalParams):
    """
    更新 DB 中的資料到最新，忽略 params 中的 start_date 與 end_date，
    只使用 exchange_id, symbol 與 timeframe。從 DB 中最後一筆資料後開始下載到目前最新的資料。
    如果 DB 不存在或無資料，則提示使用者先用 update_exchange_data 初始化 DB。
    """
    exchange = get_exchange_instance(params.exchange_id)
    db_path = get_db_path(params)
    db_min_ts, db_max_ts = get_db_interval(db_path)
    if db_max_ts is None:
        print("資料庫不存在或無資料，請先使用 update_exchange_data 初始化 DB。")
        return db_path
    period = timeframe_to_millis(params.timeframe)
    new_start_ts = db_max_ts + period
    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    if new_start_ts >= now_ts:
        print("資料已經更新到最新，無需更新。")
        return db_path
    start_interval_str = datetime.datetime.fromtimestamp(
        new_start_ts / 1000, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")
    end_interval_str = datetime.datetime.fromtimestamp(
        now_ts / 1000, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"更新資料區段：{start_interval_str} 到 {end_interval_str}")
    fetch_params = OHLCVFetchParams(
        exchange=exchange,
        symbol=params.symbol,
        timeframe=params.timeframe,
        since=new_start_ts,
        end_timestamp=now_ts,
    )
    new_ohlcv = fetch_ohlcv_interval(fetch_params)
    if new_ohlcv:
        df_new = ohlcv_to_dataframe(new_ohlcv, params.symbol)
        store_to_sqlite(df_new, db_path)
    else:
        print("沒有新資料更新。")
    return db_path


def export_db_data(params: OHLCVIntervalParams, excel_path: str):
    """
    從指定的 DB 中讀取 kline 資料（依照 params 的 start_date 與 end_date 進行篩選，
    並以日期排序），然後將結果存成 Excel 檔。
    """
    db_path = get_db_path(params)
    if not os.path.exists(db_path):
        print(f"資料庫 {db_path} 不存在。")
        return
    # 組合查詢的日期條件，注意：這裡假設資料庫中 datetime 格式為 "YYYY-MM-DD HH:MM:SS"
    start_dt_str = params.start_date + " 00:00:00"
    end_dt_str = params.end_date + " 23:59:59"
    query = f"SELECT * FROM kline WHERE datetime >= '{start_dt_str}' AND datetime <= '{end_dt_str}' ORDER BY datetime ASC"
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    df.to_excel(excel_path, index=False)
    print(f"資料已輸出到 {excel_path}")


def print_db_data(params: OHLCVIntervalParams):
    """
    從指定的 DB 中讀取 kline 資料（依照 params 的 start_date 與 end_date 進行篩選，
    並以日期排序），然後直接印出。
    """
    db_path = get_db_path(params)
    if not os.path.exists(db_path):
        print(f"資料庫 {db_path} 不存在。")
        return
    start_dt_str = params.start_date + " 00:00:00"
    end_dt_str = params.end_date + " 23:59:59"
    query = f"SELECT * FROM kline WHERE datetime >= '{start_dt_str}' AND datetime <= '{end_dt_str}' ORDER BY datetime ASC"
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    print(df)


# ------------------ __main__ 測試 ------------------
if __name__ == "__main__":
    # binance 可用的 timeframe: '1s', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M'
    # 測試用的常數設定 (注意：update_exchange_uptodate 會忽略 start_date 與 end_date)
    params = OHLCVIntervalParams(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        start_date="2025-01-01",  # 這裡的日期會被忽略
        end_date="2025-02-10",  # 這裡的日期會被忽略
    )

    # 更新資料 (僅下載缺少區段)
    # update_exchange_data(params)

    # 如果 DB 已經存在且有資料，可以用此函數更新到最新資料
    # update_exchange_uptodate(params)

    # 也可以用以下函數印出或匯出 DB 內的資料
    # print_db_data(params)
    # export_db_data(params, excel_path="kline_data.xlsx")

    symbols = [
        "BTC/USDT",
        "ETH/USDT",
        "XRP/USDT",
        "SOL/USDT",
        "ADA/USDT",
        "DOGE/USDT",
    ]

    timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
    timeframes = ["1h", "4h", "1d"]

    for s in symbols:
        for t in timeframes:
            params = OHLCVIntervalParams(
                exchange_id="binance",
                symbol=s,
                timeframe=t,
                start_date="2000-01-01",
                end_date="2025-03-11",
            )

            update_exchange_data(params)
