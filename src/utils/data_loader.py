import ccxt
import pandas as pd
from sqlalchemy import create_engine
import time
import os

# ---------------------------
# 模組內部的常數設定
# ---------------------------
DEFAULT_DB_CONFIG = {
    "host": "iroilong.synology.me",
    "port": 33067,
    "user": "crypto",
    "password": "Crypto888#",
    "database": "crypto_db",
}

DEFAULT_LOCAL_DB_DIR = "./data/sqlite_db"
DEFAULT_CSV_DIR = "./data/csv_data"


class DataLoader:
    """
    DataLoader 用於下載、儲存與載入歷史 K 線資料。
    支援多個資料來源：
      - CCXT：直接從交易所 API 下載（例如 binance）
      - nas_db：從 NAS 上的 MariaDB 資料庫讀取
      - local_db：從本地的 SQLite 資料庫讀取
      - csv：從 CSV 檔案讀取

    本模組將 db_config、local_db_dir 與 csv_dir 定義為常數，
    外部只需傳入交易所參數 exchange_config，如：
        {"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "1m"}
    """

    def __init__(self):
        # 使用模組常數初始化
        self.db_config = DEFAULT_DB_CONFIG
        self.local_db_dir = DEFAULT_LOCAL_DB_DIR
        self.csv_dir = DEFAULT_CSV_DIR

        # 如果提供了 NAS DB 的設定，就建立 MariaDB 的引擎連線
        if self.db_config:
            self.engine = self._create_nas_engine()
        else:
            self.engine = None

    def _create_nas_engine(self):
        """
        利用 SQLAlchemy 建立 NAS 資料庫的連線引擎 (MariaDB)
        """
        connection_str = (
            f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}"
            f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        )
        engine = create_engine(connection_str, echo=False)
        return engine

    def _create_sqlite_engine(self, table_name: str):
        """
        建立本地 SQLite 資料庫的連線引擎，
        檔案名稱為 {table_name}.sqlite，並存放在 local_db_dir 目錄下。
        """
        if not self.local_db_dir:
            raise ValueError("請提供 local_db_dir 用於 SQLite 資料庫儲存")
        os.makedirs(self.local_db_dir, exist_ok=True)
        file_path = os.path.join(self.local_db_dir, f"{table_name}.sqlite")
        connection_str = f"sqlite:///{file_path}"
        engine = create_engine(connection_str, echo=False)
        return engine

    @staticmethod
    def generate_table_name(exchange_config: dict) -> str:
        """
        根據 exchange_config 中的 exchange_id, symbol 與 timeframe 組合出統一的表格名稱，
        例如 {"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "1d"} 產生 "binance_BTC_USDT_1d"。
        """
        return f"{exchange_config['exchange_id']}_{exchange_config['symbol'].replace('/', '_')}_{exchange_config['timeframe']}"

    def load_data(
        self,
        exchange_config: dict,
        destination: str = "ccxt",
        start_time: str = None,
        end_time: str = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        載入歷史 K 線資料。
        參數:
            exchange_config (dict): 包含 exchange_id, symbol, timeframe 的字典。
            destination (str): 資料來源 ("ccxt", "nas_db", "local_db", "csv")
            start_time (str): 起始時間 (格式："YYYY-MM-DD HH:MM:SS")
            end_time (str): 結束時間 (格式："YYYY-MM-DD HH:MM:SS")
        Returns:
            pd.DataFrame: 包含欄位 datetime, open, high, low, close, volume, symbol
        """
        t0 = time.time()

        # 利用 exchange_config 產生統一的表格名稱
        table_name = DataLoader.generate_table_name(exchange_config)

        if destination == "ccxt":
            # 從交易所下載資料，需指定 start_time 與 end_time
            if start_time is None or end_time is None:
                raise ValueError(
                    "使用 ccxt 時，必須指定 start_time 與 end_time (格式：YYYY-MM-DD HH:MM:SS)"
                )
            # 轉換為 ISO8601 格式 (例如："2025-03-03T00:00:00Z")
            start_iso = f"{start_time.replace(' ', 'T')}Z"
            end_iso = f"{end_time.replace(' ', 'T')}Z"

            # 建立交易所物件
            exchange_id = exchange_config.get("exchange_id")
            symbol = exchange_config.get("symbol")
            timeframe = exchange_config.get("timeframe")
            if not all([exchange_id, symbol, timeframe]):
                raise ValueError(
                    "exchange_config 必須包含 exchange_id, symbol, timeframe"
                )
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({"enableRateLimit": True})
            start_ts = exchange.parse8601(start_iso)
            end_ts = exchange.parse8601(end_iso)

            all_ohlcv = []
            since = start_ts
            limit = 1000
            while since < end_ts:
                try:
                    ohlcv = exchange.fetch_ohlcv(
                        symbol, timeframe, since=since, limit=limit
                    )
                except Exception as e:
                    print(f"Error fetching data: {e}")
                    break
                if not ohlcv:
                    break
                all_ohlcv += ohlcv
                last_timestamp = ohlcv[-1][0]
                if last_timestamp == since:
                    break  # 防止無限迴圈
                since = last_timestamp + 1
                time.sleep(exchange.rateLimit / 1000)
                if since >= end_ts:
                    break

            df = pd.DataFrame(
                all_ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            df.drop(columns=["timestamp"], inplace=True)
            df["symbol"] = symbol
            df = df[["datetime", "open", "high", "low", "close", "volume", "symbol"]]

        elif destination == "nas_db":
            engine = self.engine
            try:
                conditions = []
                if start_time:
                    conditions.append(f"datetime >= '{start_time}'")
                if end_time:
                    conditions.append(f"datetime <= '{end_time}'")
                if conditions:
                    where_clause = " WHERE " + " AND ".join(conditions)
                    query = f"SELECT * FROM {table_name}{where_clause}"
                    df = pd.read_sql_query(query, con=engine)
                else:
                    df = pd.read_sql_table(table_name, con=engine)
            except Exception as e:
                print(f"Error loading from NAS DB: {e}")
                return pd.DataFrame()

        elif destination == "local_db":
            engine = self._create_sqlite_engine(table_name)
            try:
                conditions = []
                if start_time:
                    conditions.append(f"datetime >= '{start_time}'")
                if end_time:
                    conditions.append(f"datetime <= '{end_time}'")
                if conditions:
                    where_clause = " WHERE " + " AND ".join(conditions)
                    query = f"SELECT * FROM {table_name}{where_clause}"
                    df = pd.read_sql_query(query, con=engine)
                else:
                    df = pd.read_sql_table(table_name, con=engine)
            except Exception as e:
                print(f"Error loading from local DB: {e}")
                return pd.DataFrame()

        elif destination == "csv":
            if not self.csv_dir:
                raise ValueError("請設定 csv_dir 用於 CSV 讀取")
            try:
                file_path = os.path.join(self.csv_dir, f"{table_name}.csv")
                df = pd.read_csv(file_path)
                if start_time or end_time:
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    if start_time:
                        start_dt = pd.to_datetime(start_time)
                        df = df[df["datetime"] >= start_dt]
                    if end_time:
                        end_dt = pd.to_datetime(end_time)
                        df = df[df["datetime"] <= end_dt]
                    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"Error loading from CSV: {e}")
                return pd.DataFrame()
        else:
            print(f"未知的目的地: {destination}")
            return pd.DataFrame()

        elapsed_time = time.time() - t0

        # 列印下載資訊，共 5 行
        print(f"資料表名稱: {table_name}")
        print(f"下載方式: {destination}")
        print(f"資料起始時間: {start_time}")
        print(f"資料終止時間: {end_time}")
        print(f"下載資料花費時間: {elapsed_time:.2f} 秒")

        df = df[(df["datetime"] >= start_time) & (df["datetime"] <= end_time)]
        return df

    def save_data(self, df: pd.DataFrame, table_name: str, destination: str = "nas_db"):
        """
        將 DataFrame 格式的資料儲存到指定的目的地，
        支援 "nas_db"、"local_db"、"csv" 三種方式。
        """
        if destination == "nas_db":
            try:
                df.to_sql(table_name, con=self.engine, if_exists="replace", index=False)
                print(f"資料已儲存到 NAS 資料表 {table_name}")
            except Exception as e:
                print(f"Error saving to NAS DB: {e}")
        elif destination == "local_db":
            try:
                engine = self._create_sqlite_engine(table_name)
                df.to_sql(table_name, con=engine, if_exists="replace", index=False)
                print(f"資料已儲存到本地 SQLite 資料表 {table_name}")
            except Exception as e:
                print(f"Error saving to SQLite DB: {e}")
        elif destination == "csv":
            if not self.csv_dir:
                raise ValueError("請設定 csv_dir 用於 CSV 儲存")
            try:
                os.makedirs(self.csv_dir, exist_ok=True)
                file_path = os.path.join(self.csv_dir, f"{table_name}.csv")
                df.to_csv(file_path, index=False)
                print(f"資料已儲存到 CSV 檔案 {file_path}")
            except Exception as e:
                print(f"Error saving to CSV: {e}")
        else:
            print(f"未知的目的地: {destination}")

    def update_nas_data(self, exchange_config: dict) -> None:
        """
        更新 NAS DB 中資料至目前時間（僅補齊最新的後續資料）。

        流程：
        1. 根據 exchange_config 產生資料表名稱。
        2. 查詢 NAS DB 中該表格的最新 datetime 值，若無資料表或該表無任何資料，
           則印出提示訊息，不進行資料下載。
        3. 如果有資料，則將最新的 datetime 加 1 秒作為起始時間，並以目前時間作為結束時間，
           呼叫 load_data() 下載該區間內的新資料。
        4. 如果有新資料，則以 append 模式將新資料加入到 NAS DB 中的資料表。

        參數：
            exchange_config (dict): 包含 exchange_id, symbol, timeframe 的字典。
            default_start_time (str): 若資料表不存在，提供預設的起始時間（格式："YYYY-MM-DD HH:MM:SS"）。
                                       ※本方法要求若無資料表則不進行下載，因此此參數不再使用。
        """
        # 利用 exchange_config 產生統一的資料表名稱
        table_name = DataLoader.generate_table_name(exchange_config)

        # 準備 SQL 查詢語句，用以取得資料表中最新的 datetime
        query = f"SELECT MAX(datetime) AS max_dt FROM {table_name}"

        try:
            # 執行 SQL 查詢
            result = pd.read_sql_query(query, con=self.engine)
        except Exception as e:
            # 如果查詢失敗，通常代表資料表不存在
            print(f"資料表 {table_name} 不存在，無法更新資料，請先建立資料表。")
            return  # 結束更新動作

        # 檢查查詢結果是否有資料，若資料表存在但沒有任何資料，則不進行更新
        max_dt = result["max_dt"].iloc[0] if not result.empty else None
        if max_dt is None or pd.isnull(max_dt):
            print(f"資料表 {table_name} 中無任何資料，無法更新。")
            return  # 結束更新動作

        # 將資料庫中最新的時間加 1 秒，避免重複下載該筆資料
        new_start_time = (pd.to_datetime(max_dt) + pd.Timedelta(seconds=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        # 以目前系統時間作為結束時間
        now_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

        # 如果最新時間已達到或超過目前時間，則表示資料已最新，不需要更新
        if new_start_time >= now_time:
            print("資料已更新到目前時間，無需更新。")
            return

        # 列印更新區間的提示資訊
        print(
            f"從 NAS DB 表格 {table_name} 最後資料時間 {max_dt} 更新到目前時間 {now_time}。"
        )

        # 利用 ccxt 下載新資料（此處使用 load_data，下載方式為 "ccxt"）
        new_data = self.load_data(
            exchange_config=exchange_config,
            destination="ccxt",
            start_time=new_start_time,
            end_time=now_time,
        )

        # 如果下載的新資料為空，則直接列印訊息
        if new_data.empty:
            print("無新資料可更新。")
            return

        try:
            # 將新資料以 append 模式新增到 NAS DB 中相應的資料表
            new_data.to_sql(
                table_name, con=self.engine, if_exists="append", index=False
            )
            print(f"已更新 {len(new_data)} 筆資料到 NAS DB 表格 {table_name}。")
        except Exception as e:
            print(f"更新 NAS DB 失敗：{e}")


# -------------------------------------------------------------------
# 測試範例
if __name__ == "__main__":
    # 測試範例：僅需傳入交易所參數 exchange_config
    exchange_config = {
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    }
    # tablename = DataLoader.generate_table_name(exchange_config)
    # print(f"使用的資料表名稱: {tablename}")

    data_loader = DataLoader()

    # df = data_loader.load_data(
    #     exchange_config=exchange_config,
    #     destination="ccxt",
    #     start_time="2025-03-03 00:00:00",
    #     end_time="2025-03-08 15:59:59",
    # )
    # print(df.head())

    # 測試更新 nas_db：更新資料至目前時間，如果表格無資料，請提供 default_start_time
    data_loader.update_nas_data(exchange_config)
