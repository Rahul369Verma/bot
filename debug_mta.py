import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta

def debug_mta_logic():
    print("--- Starting MTA Debug ---")
    
    # 1. Create Dummy Data
    dates = pd.date_range(start='2024-01-01 09:15', end='2024-01-05 15:30', freq='5min')
    df_5m = pd.DataFrame({
        'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 1000
    }, index=dates)
    # Make it trend up
    df_5m['close'] = np.linspace(100, 200, len(df_5m))
    
    dates_15m = pd.date_range(start='2024-01-01 09:15', end='2024-01-05 15:30', freq='15min')
    df_15m = pd.DataFrame({
        'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 3000
    }, index=dates_15m)
    df_15m['close'] = np.linspace(100, 200, len(df_15m))
    
    dates_1h = pd.date_range(start='2024-01-01 09:15', end='2024-01-05 15:30', freq='1h')
    df_1h = pd.DataFrame({
        'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 12000
    }, index=dates_1h)
    df_1h['close'] = np.linspace(100, 200, len(df_1h))
    
    print(f"5m Data: {len(df_5m)} rows")
    print(f"15m Data: {len(df_15m)} rows")
    print(f"1h Data: {len(df_1h)} rows")
    
    # 2. Calculate Indicators (Simulating prepare_data)
    ema_short = 9
    ema_long = 15
    
    df_15m['ema_short_15m'] = df_15m['close'].ewm(span=ema_short, adjust=False).mean()
    df_15m['ema_long_15m'] = df_15m['close'].ewm(span=ema_long, adjust=False).mean()
    
    df_1h['ema_short_1h'] = df_1h['close'].ewm(span=ema_short, adjust=False).mean()
    df_1h['ema_long_1h'] = df_1h['close'].ewm(span=ema_long, adjust=False).mean()
    
    # 3. Merge
    print("\nMerging...")
    df_5m['15m_timestamp'] = df_5m.index.floor('15min')
    df_5m = pd.merge(df_5m, df_15m[['ema_short_15m', 'ema_long_15m']], left_on='15m_timestamp', right_index=True, how='left')
    
    # Fix for 1h candles starting at 09:15
    # Logic: (Time - 15m).floor('1h') + 15m
    df_5m['1h_timestamp'] = (df_5m.index - pd.Timedelta(minutes=15)).floor('1h') + pd.Timedelta(minutes=15)
    df_5m = pd.merge(df_5m, df_1h[['ema_short_1h', 'ema_long_1h']], left_on='1h_timestamp', right_index=True, how='left')
    
    # Forward fill
    df_5m.ffill(inplace=True)
    
    print("Merge Complete.")
    print("NaNs in ema_short_15m:", df_5m['ema_short_15m'].isna().sum())
    print("NaNs in ema_short_1h:", df_5m['ema_short_1h'].isna().sum())
    
    if df_5m['ema_short_15m'].isna().all():
        print("CRITICAL: All 15m EMAs are NaN! Merge failed.")
        print("Sample 5m Index:", df_5m.index[:5])
        print("Sample 15m Index:", df_15m.index[:5])
        print("Sample 15m_timestamp col:", df_5m['15m_timestamp'].head())
        return

    # 4. Calculate 5m Indicators
    df_5m['ema_short'] = df_5m['close'].ewm(span=ema_short, adjust=False).mean()
    df_5m['ema_long'] = df_5m['close'].ewm(span=ema_long, adjust=False).mean()
    df_5m.ta.rsi(length=14, append=True)
    df_5m.ta.adx(length=14, append=True)
    df_5m.rename(columns={'RSI_14': 'rsi', 'ADX_14': 'adx'}, inplace=True)
    
    # 5. Generate Signals (Simulating loop)
    print("\nGenerating Signals...")
    signals = 0
    
    for i in range(50, len(df_5m)):
        current = df_5m.iloc[i]
        prev = df_5m.iloc[i-1]
        
        # Trend conditions
        is_1h_uptrend = current['ema_short_1h'] > current['ema_long_1h']
        is_15m_uptrend = current['ema_short_15m'] > current['ema_long_15m']
        is_5m_uptrend = current['ema_short_5m'] > current['ema_long_5m'] if 'ema_short_5m' in current else True # Mock
        
        # Signal conditions (5m Crossover)
        is_5m_bullish_cross = (prev['ema_short'] <= prev['ema_long']) and (current['ema_short'] > current['ema_long'])
        
        if is_5m_bullish_cross:
            print(f"Cross at {df_5m.index[i]}")
            print(f"  1h Up: {is_1h_uptrend} ({current['ema_short_1h']:.2f} > {current['ema_long_1h']:.2f})")
            print(f"  15m Up: {is_15m_uptrend} ({current['ema_short_15m']:.2f} > {current['ema_long_15m']:.2f})")
            
            if is_15m_uptrend and is_1h_uptrend:
                signals += 1
                print("  >>> SIGNAL GENERATED <<<")
                
    print(f"\nTotal Signals: {signals}")

if __name__ == "__main__":
    debug_mta_logic()
