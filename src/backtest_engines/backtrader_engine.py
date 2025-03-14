import backtrader as bt
import pandas as pd
import time
from .abstract_engine import BacktestingEngine


class BacktraderEngine(BacktestingEngine):
    """
    使用 Backtrader 進行回測的引擎實作，統一回傳格式
    """

    def run_strategy(self, strategy, data: pd.DataFrame, **kwargs) -> dict:
        t0 = time.time()

        cerebro = bt.Cerebro()

        # Broker 參數
        initial_capital = kwargs.get("initial_capital", 10000)
        commission = kwargs.get("commission", 0.001)
        cerebro.broker.setcash(initial_capital)
        cerebro.broker.setcommission(commission=commission)

        # 若有 sizer 參數，加入 sizer
        sizer_percent = None
        if "sizer" in kwargs and "sizer_params" in kwargs:
            cerebro.addsizer(kwargs["sizer"], **kwargs["sizer_params"])
            sp = kwargs["sizer_params"]
            sizer_percent = sp.get("percents", sp.get("fixed_percent", None))

        # 過濾不屬於策略初始化的參數
        strategy_kwargs = kwargs.copy()
        for key in ["initial_capital", "commission", "sizer", "sizer_params", "plot"]:
            strategy_kwargs.pop(key, None)

        cerebro.addstrategy(strategy, **strategy_kwargs)

        # 檢查資料是否有 'datetime' 欄位，若無則檢查索引名稱
        if "datetime" not in data.columns:
            if data.index.name == "datetime":
                data = data.reset_index()
            else:
                raise KeyError("資料中必須包含 'datetime' 欄位或索引名稱為 'datetime'")
        if not pd.api.types.is_datetime64_any_dtype(data["datetime"]):
            data["datetime"] = pd.to_datetime(data["datetime"])
        data.set_index("datetime", inplace=True)
        datafeed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(datafeed)

        cerebro_run = cerebro.run()
        elapsed = time.time() - t0

        if kwargs.get("plot", False):
            cerebro.plot()

        final_value = cerebro.broker.getvalue()
        profit = final_value - initial_capital
        profit_rate = (profit / initial_capital) * 100.0

        # 取得策略實例並呼叫 get_result()（若有實作）
        strat_instance = cerebro_run[0]
        custom_result = {}
        if hasattr(strat_instance, "get_result") and callable(
            strat_instance.get_result
        ):
            custom_result = strat_instance.get_result()

        result = {
            "backtest_start_date": data.index.min().strftime("%Y-%m-%d %H:%M:%S"),
            "backtest_end_date": data.index.max().strftime("%Y-%m-%d %H:%M:%S"),
            "starting_cash": initial_capital,
            "percent": sizer_percent,
            "final_value": final_value,
            "profit": profit,
            "profit_rate": profit_rate,
            "buy_count": custom_result.get("buy_count"),
            "sell_count": custom_result.get("sell_count"),
            "total_commission": custom_result.get("total_commission"),
            "elapsed": elapsed,
            # 自訂結果（依策略 get_result() 回傳內容）
        }
        # 合併策略自訂結果（不重複共通欄位）
        result.update(custom_result)
        return result
