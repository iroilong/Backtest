import backtrader as bt
import pandas as pd
import time
from .abstract_engine import BacktestingEngine


class BacktraderEngine(BacktestingEngine):
    """
    使用 Backtrader 進行回測的引擎實作。
    繼承 BacktestingEngine 並實作 run_strategy。
    """

    def run_strategy(self, strategy, data: pd.DataFrame, **kwargs) -> dict:
        t0 = time.time()  # 開始計時

        cerebro = bt.Cerebro()

        # 取得 broker 參數
        initial_capital = kwargs.get("initial_capital", 10000)
        commission = kwargs.get("commission", 0.001)
        cerebro.broker.setcash(initial_capital)
        cerebro.broker.setcommission(commission=commission)

        # 如果有指定下單數量設定，加入 sizer
        if "sizer" in kwargs and "sizer_params" in kwargs:
            cerebro.addsizer(kwargs["sizer"], **kwargs["sizer_params"])

        # 保留 sizer_params 內的百分比，作為 percent 欄位
        sizer_percent = None
        if "sizer_params" in kwargs and "percents" in kwargs["sizer_params"]:
            sizer_percent = kwargs["sizer_params"]["percents"]

        # 過濾不屬於策略初始化的參數
        strategy_kwargs = kwargs.copy()
        for key in ["initial_capital", "commission", "sizer", "sizer_params", "plot"]:
            strategy_kwargs.pop(key, None)

        cerebro.addstrategy(strategy, **strategy_kwargs)

        # 若資料中不含 "datetime" 欄位，但索引名稱為 "datetime"，則重設索引
        if "datetime" not in data.columns:
            if data.index.name == "datetime":
                data = data.reset_index()
            else:
                raise KeyError("資料中必須包含 'datetime' 欄位或索引名稱為 'datetime'")

        # 確保 datetime 欄位為 datetime 型態
        if not pd.api.types.is_datetime64_any_dtype(data["datetime"]):
            data["datetime"] = pd.to_datetime(data["datetime"])

        # 記錄回測開始與結束時間（根據資料）
        backtest_start_date = data["datetime"].min().strftime("%Y-%m-%d %H:%M:%S")
        backtest_end_date = data["datetime"].max().strftime("%Y-%m-%d %H:%M:%S")

        data.set_index("datetime", inplace=True)
        datafeed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(datafeed)

        cerebro_run = cerebro.run()

        # 是否繪圖
        if kwargs.get("plot", False):
            cerebro.plot()

        final_value = cerebro.broker.getvalue()
        profit = final_value - initial_capital
        profit_rate = (profit / initial_capital) * 100.0
        elapsed = time.time() - t0

        # 取得策略實例並嘗試呼叫自訂結果方法
        strat_instance = cerebro_run[0]
        custom_result = {}
        if hasattr(strat_instance, "get_result") and callable(
            strat_instance.get_result
        ):
            custom_result = strat_instance.get_result()

        # 補充 SMA 策略自訂結果（若策略未回報，則從策略參數中取）
        short_period = custom_result.get(
            "short_period", strategy_kwargs.get("short_period")
        )
        long_period = custom_result.get(
            "long_period", strategy_kwargs.get("long_period")
        )

        result = {
            "backtest_start_date": backtest_start_date,
            "backtest_end_date": backtest_end_date,
            "starting_cash": initial_capital,
            "percent": sizer_percent,
            "final_value": final_value,
            "profit": profit,
            "profit_rate": profit_rate,
            "buy_count": custom_result.get("buy_count"),
            "sell_count": custom_result.get("sell_count"),
            "total_commission": custom_result.get("total_commission"),
            "elapsed": elapsed,
            # SMA 自訂結果
            "short_period": short_period,
            "long_period": long_period,
        }
        return result
