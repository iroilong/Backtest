import abc
import pandas as pd


class BacktestingEngine(abc.ABC):
    """
    回測引擎的抽象基底類別，定義統一接口。
    所有回測引擎都應該繼承並實作 run_strategy 方法。
    """

    @abc.abstractmethod
    def run_strategy(self, strategy, data: pd.DataFrame, **kwargs) -> dict:
        """
        執行策略回測，並回傳統一格式的回測結果。

        :param strategy: 策略類別或策略實例（依照具體實作而定）
        :param data: 回測所需的歷史資料，格式為 pandas DataFrame
        :param kwargs: 其他回測引擎需要的參數，例如 initial_capital、commission 等
        :return: 回測結果，建議為 dict，至少包含:
                 {
                     "final_value": float,    # 最終資產價值
                     "other_metrics": ...,    # 其他可選的績效指標或交易紀錄
                 }
        """
        pass
