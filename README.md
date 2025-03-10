# Backtest Project

## 📌 專案介紹
本專案用於回測不同交易策略，使用 Python 進行資料處理、策略測試，並儲存結果。
主要使用 **SQLite** 作為 K 線數據存儲，並支援圖表分析與報告匯出。

## 📂 專案架構
```
backtest_project/
│── .gitignore            # 忽略不必要的檔案
│── venv/                 # Python 虛擬環境
│── src/                  # **程式碼主目錄**
│   │── __init__.py       # 讓 `src` 成為 Python package
│   │── backtest.py       # 主回測程式
│   │── strategies/       # 存放回測策略
│   │   ├── __init__.py
│   │   ├── strategy_1.py     
│   │   ├── strategy_2.py     
│   │── utils/            # 工具函式
│   │   ├── __init__.py
│   │   ├── db.py             
│   │   ├── data_loader.py    
│── data/                 # 存放 K 線數據
│   │── kline.sqlite      # SQLite 資料庫
│   │── raw_data/         # 原始 CSV / JSON
│── results/              # 儲存回測結果
│   │── reports/          # 儲存回測報告 (PDF, DOCX)
│   │── plots/            # 儲存分析圖表 (PNG, JPG)
│── docs/                 # 技術文件、市場報告
│── requirements.txt      # 依賴套件清單
│── README.md             # 專案介紹
```

## 🚀 安裝與執行方式

### **1️⃣ 建立虛擬環境並安裝套件**
```sh
cd backtest_project
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### **2️⃣ 初始化 SQLite 資料庫**
```sh
python src/utils/db.py
```

### **3️⃣ 載入測試 K 線數據**
```sh
python src/utils/data_loader.py
```

### **4️⃣ 執行回測策略**
```sh
python src/strategies/strategy_1.py
```

## 📊 回測結果儲存
- **回測報告** (`results/reports/`)
- **回測圖表** (`results/plots/`)
- **回測 Excel/CSV** (`results/`)

## 📚 文件與研究資料
- **技術文件、回測策略研究報告** (`docs/`)
- **市場分析報告、交易策略文件** (`docs/`)

## 🔍 目標與擴充計畫
- [ ] 支援更多 K 線數據來源（API 爬取、歷史 CSV）
- [ ] 新增不同回測策略（均線策略、動能策略、機器學習）
- [ ] 增加回測報告自動產生功能
- [ ] 視覺化交易訊號，產生更詳細的回測圖表

## 🤝 貢獻方式
如果你有新的策略或改進建議，請 Fork 專案並提交 Pull Request！

