"""
程式概要說明:
    此模組負責下載、儲存與載入歷史 K 線資料，支援多個資料來源：
      - CCXT：從交易所 API（例如 binance）下載資料
      - nas_db：從 NAS 上的 MariaDB 資料庫讀取資料
      - local_db：從本地的 SQLite 資料庫讀取資料
      - csv：從 CSV 檔案讀取資料
    模組內部定義了預設的資料庫連線設定、SQLite 與 CSV 儲存目錄，
    外部使用者僅需傳入包含交易所參數的 exchange_config（例如 {"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "1m"}）。
"""

import ccxt
import pandas as pd
from sqlalchemy import create_engine
import time
import os

# ---------------------------
# 模組內部的常數設定
# ---------------------------
DEFAULT_DB_CONFIG = {
    "host": "iroilong.synology.me",  # 資料庫主機位址
    "port": 33067,  # 資料庫埠號
    "user": "crypto",  # 資料庫使用者名稱
    "password": "Crypto888#",  # 資料庫密碼
    "database": "crypto_db",  # 資料庫名稱
}

DEFAULT_LOCAL_DB_DIR = "./data/sqlite_db"  # 本地 SQLite 資料庫存放目錄
DEFAULT_CSV_DIR = "./data/csv_data"  # CSV 檔案存放目錄


class DataLoader:
    """
    DataLoader 用於下載、儲存與載入歷史 K 線資料。
    支援多個資料來源：
      - CCXT：直接從交易所 API 下載資料（例如 binance）
      - nas_db：從 NAS 上的 MariaDB 資料庫讀取資料
      - local_db：從本地的 SQLite 資料庫讀取資料
      - csv：從 CSV 檔案讀取資料

    本模組將 db_config、local_db_dir 與 csv_dir 定義為常數，
    外部只需傳入交易所參數 exchange_config，如：
        {"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "1m"}
    """

    def __init__(self):
        # 使用模組常數初始化設定參數
        self.db_config = DEFAULT_DB_CONFIG
        self.local_db_dir = DEFAULT_LOCAL_DB_DIR
        self.csv_dir = DEFAULT_CSV_DIR

        # 如果提供了資料庫設定，則建立 NAS DB 的連線引擎（MariaDB）
        if self.db_config:
            self.engine = self._create_nas_engine()
        else:
            self.engine = None

    def _create_nas_engine(self):
        """
        利用 SQLAlchemy 建立 NAS 資料庫的連線引擎 (MariaDB)
        組成連線字串後建立引擎並返回
        """
        connection_str = (
            f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}"
            f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        )
        engine = create_engine(connection_str, echo=False)
        return engine

    def _create_sqlite_engine(self, table_name: str):
        """
        建立本地 SQLite 資料庫的連線引擎。
        資料庫檔案名稱為 {table_name}.sqlite，存放於 local_db_dir 目錄下。
        """
        if not self.local_db_dir:
            raise ValueError("請提供 local_db_dir 用於 SQLite 資料庫儲存")
        # 若資料夾不存在，則建立之
        os.makedirs(self.local_db_dir, exist_ok=True)
        file_path = os.path.join(self.local_db_dir, f"{table_name}.sqlite")
        connection_str = f"sqlite:///{file_path}"
        engine = create_engine(connection_str, echo=False)
        return engine

    @staticmethod
    def generate_table_name(exchange_config: dict) -> str:
        """
        根據 exchange_config 中的 exchange_id、symbol 與 timeframe 組合出統一的表格名稱。
        例如：{"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "1d"}
        產生的表格名稱為 "binance_BTC_USDT_1d"。
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
        載入歷史 K 線資料，支援從 CCXT、NAS DB、本地 SQLite 或 CSV 中讀取。

        參數:
            exchange_config (dict): 包含 exchange_id、symbol、timeframe 的字典。
            destination (str): 資料來源 ("ccxt", "nas_db", "local_db", "csv")。
            start_time (str): 起始時間，格式 "YYYY-MM-DD HH:MM:SS"。
            end_time (str): 結束時間，格式 "YYYY-MM-DD HH:MM:SS"。

        返回:
            pd.DataFrame：包含欄位 datetime、open、high、low、close、volume、symbol。
        """
        t0 = time.time()  # 記錄開始下載的時間

        # 根據 exchange_config 產生統一的表格名稱
        table_name = DataLoader.generate_table_name(exchange_config)

        if destination == "ccxt":
            # 使用 CCXT 下載資料時必須指定起始與結束時間
            if start_time is None or end_time is None:
                raise ValueError(
                    "使用 ccxt 時，必須指定 start_time 與 end_time (格式：YYYY-MM-DD HH:MM:SS)"
                )
            # 將時間轉換為 ISO8601 格式，如 "2025-03-03T00:00:00Z"
            start_iso = f"{start_time.replace(' ', 'T')}Z"
            end_iso = f"{end_time.replace(' ', 'T')}Z"

            # 從 exchange_config 取出交易所參數
            exchange_id = exchange_config.get("exchange_id")
            symbol = exchange_config.get("symbol")
            timeframe = exchange_config.get("timeframe")
            if not all([exchange_id, symbol, timeframe]):
                raise ValueError(
                    "exchange_config 必須包含 exchange_id, symbol, timeframe"
                )
            # 建立交易所物件，並啟用限速
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({"enableRateLimit": True})
            # 將 ISO 格式時間解析為時間戳（毫秒）
            start_ts = exchange.parse8601(start_iso)
            end_ts = exchange.parse8601(end_iso)

            all_ohlcv = []  # 用於儲存下載的 OHLCV 資料
            since = start_ts
            limit = 1000  # 每次請求的資料筆數上限
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
                    break  # 避免無限迴圈
                since = last_timestamp + 1  # 往後推進一毫秒
                time.sleep(exchange.rateLimit / 1000)
                if since >= end_ts:
                    break

            # 將下載的資料轉換成 DataFrame
            df = pd.DataFrame(
                all_ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            # 將 timestamp 轉換為 datetime 格式（字串格式）
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            df.drop(columns=["timestamp"], inplace=True)
            df["symbol"] = symbol
            df = df[["datetime", "open", "high", "low", "close", "volume", "symbol"]]

        elif destination == "nas_db":
            # 從 NAS DB 載入資料
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
            # 從本地 SQLite 資料庫載入資料
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
            # 從 CSV 檔案讀取資料
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

        elapsed_time = time.time() - t0  # 計算下載耗時

        # 列印下載資訊，共 5 行
        print(f"資料表名稱: {table_name}")
        print(f"下載方式: {destination}")
        print(f"資料起始時間: {start_time}")
        print(f"資料終止時間: {end_time}")
        print(f"下載資料花費時間: {elapsed_time:.2f} 秒")

        # 最後依據時間篩選
        df = df[(df["datetime"] >= start_time) & (df["datetime"] <= end_time)]
        return df

    def save_data(self, df: pd.DataFrame, table_name: str, destination: str = "nas_db"):
        """
        將 DataFrame 格式的資料儲存到指定目的地，支援 NAS DB、本地 SQLite 與 CSV。

        參數：
            df (pd.DataFrame): 要儲存的資料表
            table_name (str): 資料表名稱
            destination (str): 儲存目的地 ("nas_db", "local_db", "csv")
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
          2. 查詢 NAS DB 中該表格最新的 datetime 值，若無資料表或該表無資料，
             則印出提示訊息，不進行資料下載。
          3. 如果有資料，將最新的 datetime 加 1 秒作為起始時間，
             以目前系統時間作為結束時間，下載該區間的新資料。
          4. 若下載的新資料非空，以 append 模式將新資料加入 NAS DB 中的該資料表。

        參數：
            exchange_config (dict): 包含 exchange_id、symbol、timeframe 的字典。
        """
        # 利用 exchange_config 產生資料表名稱
        table_name = DataLoader.generate_table_name(exchange_config)

        # 準備 SQL 查詢，獲取該表最新的 datetime
        query = f"SELECT MAX(datetime) AS max_dt FROM {table_name}"

        try:
            result = pd.read_sql_query(query, con=self.engine)
        except Exception as e:
            print(f"資料表 {table_name} 不存在，無法更新資料，請先建立資料表。")
            return

        max_dt = result["max_dt"].iloc[0] if not result.empty else None
        if max_dt is None or pd.isnull(max_dt):
            print(f"資料表 {table_name} 中無任何資料，無法更新。")
            return

        # 將最新時間加 1 秒，避免重複下載
        new_start_time = (pd.to_datetime(max_dt) + pd.Timedelta(seconds=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        now_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

        if new_start_time >= now_time:
            print("資料已更新到目前時間，無需更新。")
            return

        print(
            f"從 NAS DB 表格 {table_name} 最後資料時間 {max_dt} 更新到目前時間 {now_time}。"
        )

        new_data = self.load_data(
            exchange_config=exchange_config,
            destination="ccxt",
            start_time=new_start_time,
            end_time=now_time,
        )

        if new_data.empty:
            print("無新資料可更新。")
            return

        try:
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
    data_loader = DataLoader()

    # 測試更新 NAS DB：更新資料至目前時間（若表中無資料則不下載）
    data_loader.update_nas_data(exchange_config)
