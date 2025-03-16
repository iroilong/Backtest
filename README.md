# 20250310_BackTest 專案說明

此專案主要用於透過多種策略與回測引擎，對加密貨幣（如 BTC/USDT）進行歷史資料回測、策略開發及結果分析。

## 專案目錄結構


20250310_BackTest/
├── data/
│   ├── csv_data/
│   └── sqlite_db/
├── docs/
├── results/
│   └── binance_BTC_USDT_1m_report_20250315_123825.csv
├── src/
│   ├── backtest_engines/
│   │   ├── __init__.py
│   │   ├── abstract_engine.py
│   │   └── backtrader_engine.py
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── bearish_reversal_strategy.py
│   │   └── sma_strategy.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── data_loader.py
│   │   ├── kline_plotter.py
│   │   └── debug.py
│   └── main.py
├── .gitignore
└── README.md



### 1. `data/` 目錄

- **csv_data/**  
  存放透過 DataLoader 或手動匯出的 CSV 檔案，例如各種交易所或交易對的歷史 K 線資料。  
- **sqlite_db/**  
  存放本地 SQLite 資料庫檔案，用於快取歷史資料，方便在回測時快速讀取。

### 2. `docs/` 目錄

- 用於放置相關的文件或說明檔案，例如使用手冊、API 文件、流程圖等。

### 3. `results/` 目錄

- 存放回測後的結果檔案，例如策略回測報告（CSV、HTML 等）。  
- `binance_BTC_USDT_1m_report_20250315_123825.csv`  
  範例：使用某個策略對 `BTC/USDT` 1 分鐘資料進行回測後產生的報告，包含回測期間、績效指標、交易紀錄等。

### 4. `src/` 目錄

專案的主要程式碼都在這裡，包含回測引擎、策略、工具函式以及主程式。

#### 4.1 `backtest_engines/` 資料夾

- **`__init__.py`**  
  Python package 初始化檔，使得 `backtest_engines` 成為可匯入的套件。
- **`abstract_engine.py`**  
  定義回測引擎的抽象基底類別 `BacktestingEngine`，為所有回測引擎提供統一接口。
- **`backtrader_engine.py`**  
  使用 [Backtrader](https://www.backtrader.com/) 實作的回測引擎，繼承 `abstract_engine.py` 中的 `BacktestingEngine`，並實作 `run_strategy` 方法進行回測。

#### 4.2 `strategies/` 資料夾

- **`__init__.py`**  
  Python package 初始化檔，使得 `strategies` 成為可匯入的套件。
- **`bearish_reversal_strategy.py`**  
  定義「連續陰線後等待第一根陽線進場」的反轉策略（舉例名稱）。實作回測邏輯並提供 `get_result` 取得自訂結果。
- **`sma_strategy.py`**  
  以 SMA（Simple Moving Average）為基礎的範例策略，演示如何撰寫並回測簡單均線交叉策略。

#### 4.3 `utils/` 資料夾

- **`__init__.py`**  
  Python package 初始化檔，使得 `utils` 成為可匯入的套件。
- **`data_loader.py`**  
  主要處理資料的下載、載入與儲存。支援從 CCXT、SQLite、NAS DB、CSV 等多種來源讀取與保存 K 線資料。
- **`kline_plotter.py`**  
  使用 [mplfinance](https://github.com/matplotlib/mplfinance) 或其他繪圖庫來畫出 K 線圖，以利策略結果可視化。
- **`debug.py`**  
  存放除錯或測試用的小工具函式（若有的話）。

#### 4.4 `main.py`

- 主程式入口，示範如何：
  1. 使用 `DataLoader` 從資料庫或 CSV 取得歷史 K 線資料。  
  2. 呼叫回測引擎（如 `BacktraderEngine`）並指定策略（如 `bearish_reversal_strategy` 或 `sma_strategy`）。  
  3. 輸出回測結果或繪製圖表。  

### 5. `.gitignore`

- Git 版本控制忽略檔，定義哪些檔案或資料夾不應該被納入版本控制，例如虛擬環境、快取檔、SQLite 檔等。

### 6. `README.md`

- 就是你現在看到的這份文件，說明整個專案的目錄架構及各檔案功能，方便團隊成員或後續使用者快速了解專案。

---

## 如何開始





1. **安裝環境**  
   建議使用虛擬環境（如 `venv`）或 [Conda](https://docs.conda.io/en/latest/) 建立 Python 3.x 環境後，執行：
   ```bash
   pip install -r requirements.txt
以安裝所需套件（若有 requirements.txt）。

2. 載入資料
在 main.py 中設定 DataLoader，選擇資料來源（例如 NAS DB、CSV、SQLite 或 CCXT），下載或載入歷史 K 線資料。

3. 執行回測

指定回測引擎（例如 BacktraderEngine）
選擇策略（例如 bearish_reversal_strategy 或 sma_strategy）
設定回測參數（初始資金、時間區間、手續費等）
執行回測並觀察結果（results/ 資料夾中可能會生成報表或紀錄）

4. 策略開發

在 strategies/ 新增 Python 檔案，撰寫新策略類別並實作回測邏輯與 get_result() 方法。
在 main.py 或自行撰寫的腳本中引用此策略並執行回測。

5. 結果分析

在 results/ 中查看生成的報告或使用 kline_plotter.py 等工具對回測過程進行可視化。



################### OKX Demo API ####################
"""
apikey = "87561929-75c9-4ec2-928d-caf03c1cc7a9"
secretkey = "D5CBAFD3B4B13991EED0BB0669A73582"
IP = ""
password = "Okx7513#"
備註名 = "DemoOKX"
權限 = "讀取/提現/交易"'
"""
############################################