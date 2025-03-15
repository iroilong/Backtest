import ccxt
import pandas as pd
from sqlalchemy import create_engine
import time
import os


class DataLoader:
    """
    DataLoader 用於下載、儲存與載入歷史 K 線資料。
    支援多個資料來源：
      - CCXT：直接從交易所 API 下載（例如 binance）
      - nas_db：從 NAS 上的 MariaDB 資料庫讀取
      - local_db：從本地的 SQLite 資料庫讀取
      - csv：從 CSV 檔案讀取

    使用者在初始化時可以傳入各種設定參數，例如：
      - ccxt_config：包含 exchange_id、symbol、timeframe 等交易所參數
      - db_config：包含 NAS 資料庫的連線參數
      - local_db_dir：本地 SQLite 資料庫存放的資料夾路徑
      - csv_dir：CSV 檔案儲存的資料夾路徑
    """

    def __init__(
        self,
        ccxt_config: dict,
        local_db_dir: str = None,
        csv_dir: str = None,
        db_config: dict = None,
    ):
        # 儲存傳入的設定參數，這些參數後續用於建立連線或下載資料
        self.ccxt_config = ccxt_config  # 例如：{"exchange_id": "binance", "symbol": "BTC/USDT", "timeframe": "1m"}
        self.db_config = db_config  # 例如：{"host": "xxx", "port": 33067, "user": "crypto", "password": "Crypto888#", "database": "crypto_db"}
        self.local_db_dir = (
            local_db_dir  # 本地 SQLite 資料庫檔案存放目錄，如 "./data/sqlite_db"
        )
        self.csv_dir = csv_dir  # CSV 檔案存放目錄，如 "./data/csv_data"

        # 如果提供了 NAS DB 的設定，就建立 MariaDB 的引擎連線
        if self.db_config:
            self.engine = self._create_nas_engine()
        else:
            self.engine = None

    def _create_nas_engine(self):
        """
        利用 SQLAlchemy 建立 NAS 資料庫的連線引擎 (MariaDB)
        使用 db_config 中提供的連線資訊來組成連線字串。
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
        檔案名稱會依據傳入的 table_name 命名為 {table_name}.sqlite，
        並存放在 local_db_dir 目錄下。

        Raises:
            ValueError: 若 local_db_dir 未提供則拋出錯誤。
        """
        if not self.local_db_dir:
            raise ValueError("請提供 local_db_dir 用於 SQLite 資料庫儲存")
        os.makedirs(self.local_db_dir, exist_ok=True)  # 如果資料夾不存在，則建立之
        file_path = os.path.join(self.local_db_dir, f"{table_name}.sqlite")
        connection_str = f"sqlite:///{file_path}"
        engine = create_engine(connection_str, echo=False)
        return engine

    @staticmethod
    def generate_table_name(exchange_id: str, symbol: str, timeframe: str) -> str:
        """
        根據交易所 (exchange_id)、交易對 (symbol) 與 K 線週期 (timeframe) 組合出統一的表格名稱。
        例如：exchange_id = "binance", symbol = "BTC/USDT", timeframe = "1m"
        則產生的表格名稱為： "binance_BTC_USDT_1m"

        Args:
            exchange_id (str): 交易所代號，例如 "binance"
            symbol (str): 交易對，例如 "BTC/USDT"
            timeframe (str): K 線週期，例如 "1m", "1d" 等

        Returns:
            str: 統一的表格名稱
        """
        return f"{exchange_id}_{symbol.replace('/', '_')}_{timeframe}"

    def load_data(
        self,
        table_name: str,
        destination: str = "ccxt",
        start_time: str = None,
        end_time: str = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        載入歷史 K 線資料，支援以下資料來源：
          - "ccxt": 直接從交易所 API 下載資料，需提供 start_time 與 end_time (格式："YYYY-MM-DD HH:MM:SS")
          - "nas_db": 從 NAS 上的 MariaDB 載入資料
          - "local_db": 從本地 SQLite 載入資料
          - "csv": 從 CSV 檔案載入資料

        參數說明：
          table_name (str): 資料表名稱，通常由 generate_table_name() 產生。
          destination (str): 資料來源選項，預設為 "ccxt"。
          start_time (str): 起始時間 (格式："YYYY-MM-DD HH:MM:SS")，用於過濾資料。
          end_time (str): 結束時間 (格式："YYYY-MM-DD HH:MM:SS")。

        Returns:
            pd.DataFrame: 載入後的資料表，包含至少以下欄位：
                - datetime, open, high, low, close, volume, symbol

        Notes:
            - 若使用 "ccxt" 下載資料，會依照傳入的 start_time 與 end_time 組成 ISO8601 格式，再下載資料。
            - 為確保只取得指定區間內的資料，最後會再進行一次時間篩選。
        """
        t0 = time.time()  # 記錄開始時間

        if destination == "ccxt":
            # 若選擇從交易所下載，必須設定 ccxt_config 及 start_time 與 end_time
            if self.ccxt_config is None:
                raise ValueError("請先設定 ccxt_config")
            exchange_id = self.ccxt_config.get("exchange_id")
            symbol = self.ccxt_config.get("symbol")
            timeframe = self.ccxt_config.get("timeframe")
            if not all([exchange_id, symbol, timeframe]):
                raise ValueError("ccxt_config 必須包含 exchange_id, symbol, timeframe")
            if not start_time or not end_time:
                raise ValueError(
                    "使用 ccxt 時，必須指定 start_time 與 end_time (格式：YYYY-MM-DD HH:MM:SS)"
                )
            # 轉換為 ISO8601 格式 (例如："2025-03-03T00:00:00Z")
            start_iso = f"{start_time.replace(' ', 'T')}Z"
            end_iso = f"{end_time.replace(' ', 'T')}Z"

            # 建立交易所物件
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({"enableRateLimit": True})
            start_ts = exchange.parse8601(start_iso)
            end_ts = exchange.parse8601(end_iso)

            all_ohlcv = []
            since = start_ts
            limit = 1000
            # 透過迴圈逐步下載 K 線資料
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
                # 為了避免觸發 API 限速，每次下載後稍微暫停
                time.sleep(exchange.rateLimit / 1000)
                if since >= end_ts:
                    break

            # 將下載的資料轉換成 pandas DataFrame，並設定欄位名稱
            df = pd.DataFrame(
                all_ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            # 將 timestamp 轉換成 datetime 型態，格式為 "YYYY-MM-DD HH:MM:SS"
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            df.drop(columns=["timestamp"], inplace=True)
            df["symbol"] = symbol
            # 調整欄位順序
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
            # 從 CSV 檔案載入資料
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
                    # 轉回字串格式
                    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"Error loading from CSV: {e}")
                return pd.DataFrame()
        else:
            print(f"未知的目的地: {destination}")
            return pd.DataFrame()

        elapsed_time = time.time() - t0
        print(f"load_data 耗費時間: {elapsed_time:.2f} 秒")

        # 為確保只取得指定區間內的資料，最後再過濾一次時間
        df = df[(df["datetime"] >= start_time) & (df["datetime"] <= end_time)]

        return df

    def save_data(self, df: pd.DataFrame, table_name: str, destination: str = "nas_db"):
        """
        將 DataFrame 格式的資料儲存到指定的目的地，支援三種方式：
          - "nas_db": 儲存到 NAS 上的 MariaDB (使用 SQLAlchemy engine)
          - "local_db": 儲存到本地的 SQLite 資料庫，每個表格存成一個 .sqlite 檔案
          - "csv": 儲存到 CSV 檔案

        Args:
            df (pd.DataFrame): 要儲存的資料表，格式需包含欄位：datetime, open, high, low, close, volume, symbol
            table_name (str): 資料表名稱，通常由 generate_table_name() 產生
            destination (str): 儲存目的地，預設 "nas_db"
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


# -------------------------------------------------------------------
# 測試範例
if __name__ == "__main__":
    # 以下為測試範例，用以示範如何使用 DataLoader 下載與儲存資料

    # -------------------------
    # 定義 NAS 資料庫連線設定 (MariaDB)
    # -------------------------
    db_config = {
        "host": "iroilong.synology.me",
        "port": 33067,
        "user": "crypto",
        "password": "Crypto888#",
        "database": "crypto_db",
    }

    # -------------------------
    # 定義 CCXT 參數 (下載資料時使用，不包含時間)
    # -------------------------
    ccxt_config = {
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1m",
    }

    # -------------------------
    # 定義本地資料夾：SQLite 資料庫與 CSV 檔案儲存目錄
    # -------------------------
    local_db_dir = "./data/sqlite_db"
    csv_dir = "./data/csv_data"

    # -------------------------
    # 初始化 DataLoader：傳入 ccxt_config、db_config、local_db_dir 與 csv_dir
    # -------------------------
    data_loader = DataLoader(
        ccxt_config=ccxt_config,
        db_config=db_config,
        local_db_dir=local_db_dir,
        csv_dir=csv_dir,
    )

    # -------------------------
    # 產生統一的表格名稱 (例如: binance_BTC_USDT_1m)
    # -------------------------
    table_name = DataLoader.generate_table_name(
        ccxt_config["exchange_id"],
        ccxt_config["symbol"],
        ccxt_config["timeframe"],
    )
    print(f"使用的資料表名稱: {table_name}")

    # -------------------------
    # 使用 load_data 下載資料：這裡指定從 CCXT 下載，並指定時間區間
    # -------------------------
    df = data_loader.load_data(
        table_name,
        destination="ccxt",
        start_time="2025-03-03 00:00:00",
        end_time="2025-03-05 15:59:59",
    )
    print(df.head())

    # -------------------------
    # 將下載的資料存入 NAS DB (或可依需求存入 local_db 或 csv)
    # -------------------------
    # data_loader.save_data(df, table_name, destination="nas_db")

    # ---------------------------
    # 一次可以全下的範例
    def download_a_lot():
        # 資料庫連線設定
        db_config = {
            "host": "iroilong.synology.me",
            "port": 33067,
            "user": "crypto",
            "password": "Crypto888#",
            "database": "crypto_db",
        }

        # 本地資料夾設定
        local_db_dir = "./data/sqlite_db"
        csv_dir = "./data/csv_data"

        crypto_pairs = [
            "BTC/USDT",
            "ADA/USDT",
            "DOGE/USDT",
            "ETH/USDT",
            "SOL/USDT",
            "XRP/USDT",
        ]
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
        print(type(timeframes))
        print(crypto_pairs[0])
        print(timeframes[5])

        for pair in crypto_pairs:
            for tf in timeframes:
                # ccxt 參數（不包含日期）
                ccxt_config = {
                    "exchange_id": "binance",
                    "symbol": pair,
                    "timeframe": tf,
                }

                # 初始化 DataLoader，並傳入 db_config, local_db_dir, csv_dir 與 ccxt_config
                data_loader = DataLoader(
                    ccxt_config=ccxt_config,
                    db_config=db_config,
                    local_db_dir=local_db_dir,
                    csv_dir=csv_dir,
                )
                # 產生統一的表格名稱 (例如: binance_BTC_USDT_1m)
                table_name = DataLoader.generate_table_name(
                    ccxt_config["exchange_id"],
                    ccxt_config["symbol"],
                    ccxt_config["timeframe"],
                )
                print(f"使用的資料表名稱: {table_name}")

                # 透過 load_data 下載資料 (destination 預設 "ccxt")，並指定時間區間
                df = data_loader.load_data(
                    table_name,
                    destination="ccxt",
                    start_time="2000-01-01 00:00:00",
                    end_time="2025-04-05 15:59:59",
                )

                data_loader.save_data(df, table_name, destination="nas_db")
