import ccxt
import pandas as pd
from sqlalchemy import create_engine
import time
import os


class DataLoader:
    def __init__(
        self,
        ccxt_config: dict,
        local_db_dir: str = None,
        csv_dir: str = None,
        db_config: dict = None,
    ):
        """
        初始化 DataLoader 並建立資料庫連線

        db_config 範例 (NAS DB):
            {
                "host": "iroilong.synology.me",
                "port": 33067,
                "user": "crypto",
                "password": "Crypto888#",
                "database": "crypto_db",
            }
        ccxt_config 範例:
            {
                "exchange_id": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1m"
            }
        local_db_dir: 本地 SQLite 資料庫檔案存放的資料夾，例如 "./data/sqlite_db"
        csv_dir: CSV 檔案儲存的資料夾，例如 "./data/csv_data"
        """
        self.db_config = db_config
        self.engine = self._create_nas_engine()
        self.local_db_dir = local_db_dir
        self.csv_dir = csv_dir
        self.ccxt_config = ccxt_config

    def _create_nas_engine(self):
        """
        利用 SQLAlchemy 建立 NAS 資料庫引擎 (MariaDB)
        """
        connection_str = (
            f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}"
            f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        )
        engine = create_engine(connection_str, echo=False)
        return engine

    def _create_sqlite_engine(self, table_name: str):
        """
        根據指定的 table_name 產生對應的 SQLite 引擎，
        儲存檔案會命名為 {table_name}.sqlite 並存放在 local_db_dir 內
        """
        if not self.local_db_dir:
            raise ValueError("請提供 local_db_dir 用於 SQLite 資料庫儲存")
        os.makedirs(self.local_db_dir, exist_ok=True)
        file_path = os.path.join(self.local_db_dir, f"{table_name}.sqlite")
        connection_str = f"sqlite:///{file_path}"
        engine = create_engine(connection_str, echo=False)
        return engine

    @staticmethod
    def generate_table_name(exchange_id: str, symbol: str, timeframe: str) -> str:
        """
        根據 exchange_id、symbol 與 timeframe 產生統一的表格名稱
        例如: binance_BTC_USDT_1m
        """
        return f"{exchange_id}_{symbol.replace('/', '_')}_{timeframe}"

    def load_data(
        self,
        table_name: str,
        destination: str = "ccxt",  # 四種選項："ccxt", "nas_db", "local_db", "csv"
        start_time: str = None,
        end_time: str = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        從指定來源載入資料。

        若 destination == "ccxt"：
          使用 self.ccxt_config 中的參數 (必須包含 exchange_id, symbol, timeframe)；
          並以 load_data() 傳入的 start_time 與 end_time (格式："YYYY-MM-DD HH:MM:SS") 下載資料。

        若 destination 為 "nas_db", "local_db", "csv" 則從資料庫或 CSV 讀取，
        並根據 start_time 與 end_time 過濾資料。

        計時：載入完成後會印出耗費的秒數。
        """
        t0 = time.time()

        if destination == "ccxt":
            if self.ccxt_config is None:
                raise ValueError("請先設定 ccxt_config")
            # 從 ccxt_config 取得必須參數
            exchange_id = self.ccxt_config.get("exchange_id")
            symbol = self.ccxt_config.get("symbol")
            timeframe = self.ccxt_config.get("timeframe")
            if not all([exchange_id, symbol, timeframe]):
                raise ValueError("ccxt_config 必須包含 exchange_id, symbol, timeframe")
            if not start_time or not end_time:
                raise ValueError(
                    "使用 ccxt 時，必須指定 start_time 與 end_time (格式：YYYY-MM-DD HH:MM:SS)"
                )
            # 將 start_time 與 end_time 組成 ISO8601 格式："YYYY-MM-DDTHH:MM:SSZ"
            start_iso = f"{start_time.replace(' ', 'T')}Z"
            end_iso = f"{end_time.replace(' ', 'T')}Z"

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
                    break
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
        print(f"load_data 耗費時間: {elapsed_time:.2f} 秒")

        # 再進行一次時間篩選(因為某些交易所或 API 可能會返回超出指定時間區間的完整 K 線資料)
        df = df[(df["datetime"] >= start_time) & (df["datetime"] <= end_time)]

        return df

    def save_data(self, df: pd.DataFrame, table_name: str, destination: str = "nas"):
        """
        儲存 DataFrame 至指定目的地，預設儲存至 NAS DB

        destination:
            "nas_db"    : 儲存到 NAS 上的 MariaDB
            "local_db"  : 儲存到本地 SQLite 資料庫（每個表格存成一個 .sqlite 檔案）
            "csv"       : 儲存到 CSV 檔案
        對於 local_db 與 csv，請在初始化 DataLoader 時設定 local_db_dir 與 csv_dir
        """
        if destination == "nas_db":
            try:
                df.to_sql(table_name, con=self.engine, if_exists="replace", index=False)
                print(f"資料已儲存到 NAS 資料表 {table_name}")
            except Exception as e:
                print(f"Error saving to NAS DB: {e}")
        elif destination == "local_db":
            try:
                # 使用 _create_sqlite_engine 時傳入 table_name 以建立對應的 .sqlite 檔案
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


# ---------------------------
# 測試範例
if __name__ == "__main__":
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

    # 透過 load_data 下載資料 (destination 預設 "ccxt")，並指定時間區間
    df = data_loader.load_data(
        table_name,
        destination="ccxt",
        start_time="2025-03-03 00:00:00",
        end_time="2025-03-05 15:59:59",
    )
    print(df.head())

    # 分別從三個來源存入資料（測試用）
    # data_loader.save_data(df, table_name, destination="nas_db")
    # data_loader.save_data(df, table_name, destination="local_db")
    # data_loader.save_data(df, table_name, destination="csv")

    # 分別從三個來源載入資料（測試用）
    df_nas = data_loader.load_data(
        table_name,
        destination="nas_db",
        start_time="2025-03-04 00:00:00",
        end_time="2025-03-05 15:59:59",
    )
    print(df_nas.head())
    df_sqlite = data_loader.load_data(
        table_name,
        destination="local_db",
        start_time="2025-03-05 00:00:00",
        end_time="2025-03-05 15:59:59",
    )
    print(df_sqlite.head())
    df_csv = data_loader.load_data(
        table_name,
        destination="csv",
        start_time="2025-03-03 00:00:00",
        end_time="2025-03-05 15:59:59",
    )
    print(df_csv.head())
