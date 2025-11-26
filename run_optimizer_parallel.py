import sys
import os
import pandas as pd
import random
import multiprocessing
from datetime import datetime, timedelta, time as dt_time
import time
import json
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from backtest.backtest import BacktestEngine
from fetcher.fyers_data import FyersDataManager

# --- Configuration ---
RESULTS_FILE = "optimizer_results.csv"
SYMBOL = "BANKNIFTY" # Maps to NSE:NIFTYBANK-INDEX
START_DATE = datetime(2022, 11, 1).date()
END_DATE = datetime.now().date()
NUM_ITERATIONS = 1000 # Default
NUM_PROCESSES = max(1, multiprocessing.cpu_count() - 2) # Leave some cores free

# --- Parameter Space (Synced with optimizer.py) ---
PARAM_SPACE = {
    'ema_pairs': [(9, 15), (9, 21), (10, 20), (5, 8), (9, 14), (8, 20), (8, 14)],
    'atr_period': (10, 30),
    'atr_tp_multiplier': (1.5, 5.0),
    'atr_sl_multiplier': (0.5, 2.0),
    'max_trades_per_day': (1, 10),
    'trade_start_time': (dt_time(9, 15), dt_time(11, 0)),
    'trade_end_time': (dt_time(13, 0), dt_time(15, 15)),
    'simulated_premium_pct': (0.005, 0.015),
    'simulated_delta': (0.4, 0.7),
    'rsi_period': (10, 30),
    'rsi_overbought': (65, 80),
    'rsi_oversold': (20, 35),
    'adx_period': (10, 20),
    'adx_threshold': (18, 30),
    'max_trade_duration_minutes': (15, 120),
    'trailing_sl_multiplier': (1.0, 3.0),
    'candle_size_factor': (0.5, 2.0),
}

# Global variable to hold data in workers
worker_prefetched_data = None

def random_time(start, end):
    start_ts = int(start.hour * 60 + start.minute)
    end_ts = int(end.hour * 60 + end.minute)
    rand_ts = random.randint(start_ts, end_ts)
    return dt_time(rand_ts // 60, rand_ts % 60)

def init_worker(data):
    """Initialize worker with pre-fetched data."""
    global worker_prefetched_data
    worker_prefetched_data = data

def run_simulation(params):
    """Run a single backtest simulation."""
    try:
        # Initialize engine (offline)
        engine = BacktestEngine(fyers_manager=None)
        
        # Run backtest
        result = engine.run_backtest(
            strategy_name="mta_ema_crossover",
            symbol=SYMBOL,
            start_date=START_DATE,
            end_date=END_DATE,
            interval="5",
            silent=True,
            data=None,
            backtest_mode="Simulated Premium (Fast & Approx.)",
            prefetched_data=worker_prefetched_data,
            **params
        )
        
        # Return result dict
        return {
            "Sharpe": result.sharpe_ratio,
            "Win Rate (%)": result.win_rate,
            "P&L (₹)": result.total_pnl,
            "Max DD (%)": result.max_drawdown,
            "Trades": result.total_trades,
            "ema_short": params['ema_short'],
            "ema_long": params['ema_long'],
            "atr_period": params['atr_period'],
            "tp_mult": params['atr_tp_multiplier'],
            "sl_mult": params['atr_sl_multiplier'],
            "max_trades": params['max_trades_per_day'],
            "start_time": params['trade_start_time'].strftime("%H:%M"),
            "end_time": params['trade_end_time'].strftime("%H:%M"),
            "sim_delta": params['simulated_delta'],
            "sim_prem_pct": params['simulated_premium_pct'],
            "RSI": params['rsi_period'],
            "OB": params['rsi_overbought'],
            "OS": params['rsi_oversold'],
            "ADX": params['adx_period'],
            "ADX_Th": params['adx_threshold'],
            "1H": params['use_1h_filter'],
            "30M": params['use_30m_filter'],
            "TSL": params['use_trailing_sl'],
            "TSL_Mult": params['trailing_sl_multiplier'],
            "MaxDur": params['max_trade_duration_minutes'],
            "CandleSz": params['use_candle_size_filter'],
            "SkipExp": params['skip_last_week_expiry'],
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    print(f"🚀 Starting Parallel Optimizer with {NUM_PROCESSES} processes...")
    
    # 1. Initialize Fyers & Fetch Data
    fyers_manager = FyersDataManager()
    
    # Check auth (simple check)
    if not os.path.exists("fyers_token.json"):
        print("❌ Error: fyers_token.json not found. Please login via the Streamlit app first.")
        return

    print("📥 Fetching Data (5m, 15m, 30m, 1h)...")
    prefetched_data = {}
    try:
        # 5m
        df_5m = fyers_manager.get_historical_index_data(SYMBOL, START_DATE, END_DATE, "5", is_backtest_log=True)
        if df_5m is None or df_5m.empty: raise Exception("No 5m data returned.")
        prefetched_data['5m'] = df_5m
        print(f"   ✅ 5m: {len(df_5m)} candles")
        
        # 15m
        df_15m = fyers_manager.get_historical_index_data(SYMBOL, START_DATE, END_DATE, "15", is_backtest_log=True)
        if df_15m is not None: prefetched_data['15m'] = df_15m
        print(f"   ✅ 15m: {len(df_15m)} candles")

        # 30m
        df_30m = fyers_manager.get_historical_index_data(SYMBOL, START_DATE, END_DATE, "30", is_backtest_log=True)
        if df_30m is not None: prefetched_data['30m'] = df_30m
        print(f"   ✅ 30m: {len(df_30m)} candles")

        # 1h
        df_1h = fyers_manager.get_historical_index_data(SYMBOL, START_DATE, END_DATE, "60", is_backtest_log=True)
        if df_1h is not None: prefetched_data['1h'] = df_1h
        print(f"   ✅ 1h: {len(df_1h)} candles")
        
    except Exception as e:
        print(f"❌ Data Fetch Error: {e}")
        return

    # 2. Load Existing Results
    seen_params = set()
    if os.path.exists(RESULTS_FILE):
        try:
            existing_df = pd.read_csv(RESULTS_FILE, on_bad_lines='skip')
            print(f"📂 Loaded {len(existing_df)} existing results.")
            for _, row in existing_df.iterrows():
                sig = (
                    row.get('ema_short'), row.get('ema_long'), row.get('atr_period'), 
                    row.get('tp_mult'), row.get('sl_mult'), row.get('max_trades'),
                    row.get('TSL'), row.get('TSL_Mult'), row.get('1H'), row.get('30M')
                )
                seen_params.add(sig)
        except Exception as e:
            print(f"⚠️ Error loading existing results: {e}")

    # 3. Generate Parameters
    tasks = []
    print(f"🎲 Generating {NUM_ITERATIONS} parameter combinations...")
    
    while len(tasks) < NUM_ITERATIONS:
        ema_pair = random.choice(PARAM_SPACE['ema_pairs'])
        
        params = {
            'ema_short': ema_pair[0],
            'ema_long': ema_pair[1],
            'atr_period': random.randint(PARAM_SPACE['atr_period'][0], PARAM_SPACE['atr_period'][1]),
            'atr_tp_multiplier': round(random.uniform(PARAM_SPACE['atr_tp_multiplier'][0], PARAM_SPACE['atr_tp_multiplier'][1]), 2),
            'atr_sl_multiplier': round(random.uniform(PARAM_SPACE['atr_sl_multiplier'][0], PARAM_SPACE['atr_sl_multiplier'][1]), 2),
            'max_trades_per_day': random.randint(PARAM_SPACE['max_trades_per_day'][0], PARAM_SPACE['max_trades_per_day'][1]),
            'trade_start_time': random_time(PARAM_SPACE['trade_start_time'][0], PARAM_SPACE['trade_start_time'][1]),
            'trade_end_time': random_time(PARAM_SPACE['trade_end_time'][0], PARAM_SPACE['trade_end_time'][1]),
            'simulated_premium_pct': round(random.uniform(PARAM_SPACE['simulated_premium_pct'][0], PARAM_SPACE['simulated_premium_pct'][1]), 4),
            'simulated_delta': round(random.uniform(PARAM_SPACE['simulated_delta'][0], PARAM_SPACE['simulated_delta'][1]), 2),
            'use_rsi_filter': True,
            'rsi_period': random.randint(PARAM_SPACE['rsi_period'][0], PARAM_SPACE['rsi_period'][1]),
            'rsi_overbought': random.randint(PARAM_SPACE['rsi_overbought'][0], PARAM_SPACE['rsi_overbought'][1]),
            'rsi_oversold': random.randint(PARAM_SPACE['rsi_oversold'][0], PARAM_SPACE['rsi_oversold'][1]),
            'use_adx_filter': True,
            'adx_period': random.randint(PARAM_SPACE['adx_period'][0], PARAM_SPACE['adx_period'][1]),
            'adx_threshold': random.randint(PARAM_SPACE['adx_threshold'][0], PARAM_SPACE['adx_threshold'][1]),
            'use_1h_filter': random.choice([True, False]),
            'use_30m_filter': random.choice([True, False]),
            'use_trailing_sl': random.choice([True, False]),
            'trailing_sl_multiplier': round(random.uniform(PARAM_SPACE['trailing_sl_multiplier'][0], PARAM_SPACE['trailing_sl_multiplier'][1]), 1),
            'max_trade_duration_minutes': random.randint(PARAM_SPACE['max_trade_duration_minutes'][0], PARAM_SPACE['max_trade_duration_minutes'][1]),
            'use_candle_size_filter': random.choice([True, False]),
            'candle_size_factor': round(random.uniform(PARAM_SPACE['candle_size_factor'][0], PARAM_SPACE['candle_size_factor'][1]), 1),
            'skip_last_week_expiry': random.choice([True, False]),
            'sl_mode': 'ATR', 
            'initial_capital': 20000,
        }
        
        sig = (
            params['ema_short'], params['ema_long'], params['atr_period'],
            params['atr_tp_multiplier'], params['atr_sl_multiplier'], params['max_trades_per_day'],
            params['use_trailing_sl'], params['trailing_sl_multiplier'], 
            params['use_1h_filter'], params['use_30m_filter']
        )
        
        if sig not in seen_params:
            seen_params.add(sig)
            tasks.append(params)

    # 4. Run Parallel Execution
    print(f"🔥 Starting Pool with {NUM_PROCESSES} workers...")
    start_time = time.time()
    
    with multiprocessing.Pool(processes=NUM_PROCESSES, initializer=init_worker, initargs=(prefetched_data,)) as pool:
        # Use imap_unordered for responsiveness
        results_iter = pool.imap_unordered(run_simulation, tasks)
        
        completed = 0
        profitable = 0
        
        for result in results_iter:
            completed += 1
            if "error" in result:
                print(f"❌ Error: {result['error']}")
                continue
                
            # Save to CSV immediately
            df_new = pd.DataFrame([result])
            if not os.path.exists(RESULTS_FILE):
                df_new.to_csv(RESULTS_FILE, index=False)
            else:
                df_new.to_csv(RESULTS_FILE, mode='a', header=False, index=False)
            
            # Print status
            sharpe = result.get('Sharpe', 0)
            if sharpe > 0.1: # Only print "good" ones to reduce noise
                print(f"[{completed}/{NUM_ITERATIONS}] ✅ Sharpe: {sharpe:.2f} | WR: {result['Win Rate (%)']:.1f}% | PnL: {result['P&L (₹)']:.0f}")
                profitable += 1
            else:
                if completed % 10 == 0:
                    print(f"[{completed}/{NUM_ITERATIONS}] ... processed")

    elapsed = time.time() - start_time
    print(f"\n✨ Optimization Complete! Processed {completed} iterations in {elapsed:.1f}s.")
    print(f"found {profitable} profitable strategies.")

if __name__ == "__main__":
    main()
