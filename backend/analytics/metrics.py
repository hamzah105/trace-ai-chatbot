import pandas as pd

class AnalyticsManager:
    def __init__(self):
        # Empty dataframe for metrics
        self.metrics_df = pd.DataFrame(columns=[
            "timestamp",
            "user_prompt",
            "response_time",
            "model_name",
            "tokens_used"
        ])

    def add_metric(
        self,
        timestamp,
        user_prompt,
        response_time,
        model_name,
        tokens_used
    ):
        new_row = {
            "timestamp": timestamp,
            "user_prompt": user_prompt,
            "response_time": response_time,
            "model_name": model_name,
            "tokens_used": tokens_used
        }

        self.metrics_df.loc[len(self.metrics_df)] = new_row

    def show_metrics(self):
        print(self.metrics_df)