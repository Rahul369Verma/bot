# Modified: market_analyzer.py
# This file is now a simple wrapper around the centralized strategy.

import pandas as pd
from typing import Optional, Dict, Any

# Go up from 'fetcher' (where this file lives) to 'src', 
# then down into 'backtest' to get the strategy
try:
    from ..backtest.backtest import MultiTimeframeStrategy
except ImportError:
    # Fallback for different/flat project structures
    print("Warning: Relative import failed. Trying direct import for MultiTimeframeStrategy.")
    from backtest.backtest import MultiTimeframeStrategy

class MarketAnalyzer:
    """
    Analyzes market data by wrapping the centralized Multi-Timeframe (MTA) Strategy.
    This class holds the stateful instance of the strategy for live trading.
    """
    def __init__(self):
        # This instance holds the live state (daily_trend, etc.)
        self.strategy = MultiTimeframeStrategy()

    def calculate_indicators(self, df_5min_raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        DEPRECATED: This logic is now inside the MultiTimeframeStrategy class.
        This method is kept for compatibility in case anything still calls it,
        but it just forwards the call.
        """
        print("Warning: MarketAnalyzer.calculate_indicators() is deprecated. Use the strategy instance directly.")
        return self.strategy.calculate_indicators(df_5min_raw, **self.strategy.parameters)

    def generate_trading_signal(self, historical_data: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Gets the latest trading signal from the centralized strategy object.
        """
        try:
            # The strategy instance manages its own state (daily trend, etc.)
            return self.strategy.generate_live_signal(historical_data)
        except Exception as e:
            print(f"Error in MarketAnalyzer calling strategy.generate_live_signal: {e}")
            return None