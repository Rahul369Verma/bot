# src/signals/signal_engine.py
import pandas as pd
from typing import Dict, Any, Optional

class SignalEngine:
    """
    EMA-based engine with confirmation window.
    Entry requires last candle close to be between ema_short and ema_long
    and the trend confirmed for `confirmation_candles`.
    """
    def __init__(self, ema_short: int = 9, ema_long: int = 15, confirmation_candles: int = 15):
        assert ema_short < ema_long
        self.ema_short = ema_short
        self.ema_long = ema_long
        self.confirmation_candles = confirmation_candles

    def compute_emas(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy().reset_index(drop=True)
        df["ema_short"] = df["close"].ewm(span=self.ema_short, adjust=False).mean()
        df["ema_long"] = df["close"].ewm(span=self.ema_long, adjust=False).mean()
        return df

    def trend_confirmation(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or len(df) < max(self.ema_long, self.confirmation_candles):
            return {"trend": None, "duration": 0}
        df2 = self.compute_emas(df)
        tail = df2.tail(self.confirmation_candles)
        buy_cond = (tail["ema_short"] > tail["ema_long"]).all()
        sell_cond = (tail["ema_short"] < tail["ema_long"]).all()
        dur = 0
        current_trend = None
        for i in range(len(df2)-1, -1, -1):
            if df2.loc[i,"ema_short"] > df2.loc[i,"ema_long"]:
                trend_i = "BUY"
            elif df2.loc[i,"ema_short"] < df2.loc[i,"ema_long"]:
                trend_i = "SELL"
            else:
                trend_i = None
            if i == len(df2)-1:
                current_trend = trend_i
                dur = 1 if trend_i else 0
            else:
                if trend_i == current_trend and trend_i is not None:
                    dur += 1
                else:
                    break
        if buy_cond:
            return {"trend": "BUY", "duration": dur}
        if sell_cond:
            return {"trend": "SELL", "duration": dur}
        return {"trend": None, "duration": dur}

    def last_candle_between_emas(self, df: pd.DataFrame) -> bool:
        if df is None or len(df) < self.ema_long:
            return False
        df2 = self.compute_emas(df)
        last = df2.iloc[-1]
        ema_s = last["ema_short"]
        ema_l = last["ema_long"]
        close = last["close"]
        low = min(ema_s, ema_l)
        high = max(ema_s, ema_l)
        return (close >= low) and (close <= high)

    def decide(self, candle_df: pd.DataFrame, underlying_price: float, oi_direction: Optional[str]) -> Optional[Dict[str, Any]]:
        conf = self.trend_confirmation(candle_df)
        if conf["trend"] is None:
            return None
        if not self.last_candle_between_emas(candle_df):
            return None
        atm_strike = int(round(underlying_price / 100.0) * 100)
        if oi_direction == "CE" and conf["trend"] == "BUY":
            return {"side": "BUY_CALL", "strike": atm_strike}
        if oi_direction == "PE" and conf["trend"] == "SELL":
            return {"side": "BUY_PUT", "strike": atm_strike}
        return None
# Could consider adding a minimum OI change threshold check directly inside decide() to reduce false positives.