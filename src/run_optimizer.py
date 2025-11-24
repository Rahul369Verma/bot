# FILENAME: src/run_optimizer.py
# This is your new high-speed, parallel optimizer.
# Run from your terminal: python src/run_optimizer.py

import os
import sys
import json
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dt_time
from multiprocessing import Pool, cpu_count
from dotenv import load_dotenv

# --- Add src to path ---
current_file_path = os.path.abspath(__file__)
src_dir = os.path.dirname(current_file_path)
project_root = os.path.dirname(src_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
# --- End Path Fix ---

from backtest.backtest import StrategyTester
from fetcher.fyers_data import FyersDataManager

# --- Configuration ---
load_dotenv(os.path.join(project_root, '.env')) # Load .env from root
RESULTS_FILE = "optimizer_results.json"
STRATEGY_KEY = "mta_ema_crossover"
INDEX_TO_TEST = "BANKNIFTY"

# --- Parameters to Test ---
NUM_ITERATIONS = 500 # How many random combos to test
START_DATE = datetime.now() - timedelta(days=365*2) # 2 years of data
END_DATE = datetime.now()

# --- Your Target Metrics ---
TARGET_SHARPE = 1.0
TARGET_WIN_RATE = 50.0
TARGET_MIN_TRADES = 10
TARGET_MAX_DRAWDOWN = 10.0

# --- Parameter Space ---
PARAM_SPACE = {
    'interval': ['1m', '5m'], # Optimize over interval
    'ema_short': (2, 15),
    'ema_long': (16, 50),
    'atr_period': (10, 30),
    'atr_tp_multiplier': (0.5, 5.0),
    'atr_sl_multiplier': (0.2, 2.0),
    'max_trades_per_day': (1, 10),
    'trade_start_time': (dt_time(9, 16), dt_time(12, 0)),
    'trade_end_time': (dt_time(12, 0), dt_time(15, 15)),
    # --- NEW: ADX/RSI Params ---
    'rsi_period': (10, 30),
    'rsi_overbought': (65, 80),
    'rsi_oversold': (20, 35),
    'adx_period': (10, 20),
    'adx_threshold': (18, 30)
}

def random_time(start, end):
    start_ts = int(start.hour * 60 + start.minute)
    end_ts = int(end.hour * 60 + end.minute)
    rand_ts = random.randint(start_ts, end_ts)
    return dt_time(rand_ts // 60, rand_ts % 60)

def generate_random_params():
    """Generates one set of random parameters."""
    rand_params = {
        'interval': random.choice(PARAM_SPACE['interval']),
        'ema_short': random.randint(PARAM_SPACE['ema_short'][0], PARAM_SPACE['ema_short'][1]),
        'ema_long': random.randint(PARAM_SPACE['ema_long'][0], PARAM_SPACE['ema_long'][1]),
        'atr_period': random.randint(PARAM_SPACE['atr_period'][0], PARAM_SPACE['atr_period'][1]),
        'atr_tp_multiplier': round(random.uniform(PARAM_SPACE['atr_tp_multiplier'][0], PARAM_SPACE['atr_tp_multiplier'][1]), 2),
        'atr_sl_multiplier': round(random.uniform(PARAM_SPACE['atr_sl_multiplier'][0], PARAM_SPACE['atr_sl_multiplier'][1]), 2),
        'max_trades_per_day': random.randint(PARAM_SPACE['max_trades_per_day'][0], PARAM_SPACE['max_trades_per_day'][1]),
        'trade_start_time': random_time(PARAM_SPACE['trade_start_time'][0], PARAM_SPACE['trade_start_time'][1]),
        'trade_end_time': random_time(PARAM_SPACE['trade_end_time'][0], PARAM_SPACE['trade_end_time'][1]),
        'sl_mode': 'ATR', 
        'initial_capital': 20000,
        # --- NEW: Randomize ADX/RSI params ---
        'use_rsi_filter': True,
        'rsi_period': random.randint(PARAM_SPACE['rsi_period'][0], PARAM_SPACE['rsi_period'][1]),
        'rsi_overbought': random.randint(PARAM_SPACE['rsi_overbought'][0], PARAM_SPACE['rsi_overbought'][1]),
        'rsi_oversold': random.randint(PARAM_SPACE['rsi_oversold'][0], PARAM_SPACE['rsi_oversold'][1]),
        'use_adx_filter': True,
        'adx_period': random.randint(PARAM_SPACE['adx_period'][0], PARAM_SPACE['adx_period'][1]),
        'adx_threshold': random.randint(PARAM_SPACE['adx_threshold'][0], PARAM_SPACE['adx_threshold'][1]),
        'use_dynamic_risk': True, # Enable dynamic risk by default in optimizer
    }
    if rand_params['ema_short'] >= rand_params['ema_long']:
        rand_params['ema_long'] = rand_params['ema_short'] + 1
    return rand_params

# --- Multiprocessing Init ---
# Global variables for workers
worker_data_1m = None
worker_data_5m = None

def init_worker(data_1m, data_5m):
    """Initializer to share data memory with workers."""
    global worker_data_1m, worker_data_5m
    worker_data_1m = data_1m
    worker_data_5m = data_5m

def run_backtest_wrapper(params_tuple):
    """
    A simple wrapper for multiprocessing.
    It re-initializes the non-picklable Fyers manager
    inside the child process.
    """
    iteration, total_iterations, params = params_tuple
    
    try:
        # --- Re-initialize components for this process ---
        fyers_manager = FyersDataManager()
        tester = StrategyTester(fyers_manager=fyers_manager)
        
        # Select data based on interval param
        if params['interval'] == '5m':
            data_to_use = worker_data_5m.copy()
            interval_arg = "5"
        else:
            data_to_use = worker_data_1m.copy()
            interval_arg = "1"
        
        result = tester.engine.run_backtest(
            strategy_name=STRATEGY_KEY,
            symbol=INDEX_TO_TEST,
            start_date=START_DATE,
            end_date=END_DATE,
            interval=interval_arg,
            silent=True, 
            data=data_to_use, # Pass the shared data
            **params
        )
        
        print(f"  > Iteration {iteration}/{total_iterations} [{params['interval']}]: Sharpe {result.sharpe_ratio:.2f}, WR {result.win_rate:.1f}%, Trades {result.total_trades}")

        is_good = (
            result.sharpe_ratio >= TARGET_SHARPE and
            result.win_rate > TARGET_WIN_RATE and
            result.total_trades > TARGET_MIN_TRADES and
            result.max_drawdown < TARGET_MAX_DRAWDOWN
        )
        
        if is_good:
            print(f"✅ FOUND A MATCH! Iteration {iteration}")
            return {
                "Sharpe": result.sharpe_ratio,
                "Win Rate (%)": result.win_rate,
                "P&L (₹)": result.total_pnl,
                "Max DD (%)": result.max_drawdown,
                "Trades": result.total_trades,
                "Interval": params['interval'],
                "ema_short": params['ema_short'],
                "ema_long": params['ema_long'],
                "atr_period": params['atr_period'],
                "tp_mult": params['atr_tp_multiplier'],
                "sl_mult": params['atr_sl_multiplier'],
                "max_trades": params['max_trades_per_day'],
                "start_time": params['trade_start_time'].strftime("%H:%M"),
                "end_time": params['trade_end_time'].strftime("%H:%M"),
            }
    except Exception as e:
        print(f"❌ Iteration {iteration} failed: {e}")
    
    return None

def main():
    print("--- Starting Optimizer ---")
    
    # 1. Initialize Fyers and get data ONCE
    print("Initializing Fyers Data Manager...")
    try:
        fyers_manager = FyersDataManager()
        if not fyers_manager.is_authenticated():
            print("❌ Fyers API is not authenticated.")
            print("Please run the Streamlit app, go to Settings, and generate a token first.")
            return
    except Exception as e:
        print(f"❌ Failed to initialize Fyers Manager: {e}")
        return

    print(f"Fetching {INDEX_TO_TEST} 1m data from {START_DATE.date()} to {END_DATE.date()}...")
    try:
        # Always fetch 1m data
        data_1m = fyers_manager.get_historical_index_data(INDEX_TO_TEST, START_DATE, END_DATE, "1", is_backtest_log=True)
        if data_1m is None or data_1m.empty:
            raise Exception("No data returned.")
        print(f"✅ 1m Data fetched successfully ({len(data_1m)} candles).")
        
        # Pre-calculate 5m data for optimization
        print("Pre-calculating 5m data...")
        data_5m = data_1m.resample('5min').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        print(f"✅ 5m Data generated ({len(data_5m)} candles).")
        
    except Exception as e:
        print(f"❌ Failed to fetch data: {e}")
        return

    # 2. Generate all parameter sets
    print(f"Generating {NUM_ITERATIONS} random parameter sets...")
    param_list = [generate_random_params() for _ in range(NUM_ITERATIONS)]
    
    # 3. Create a list of tasks for the pool (params only, data is shared)
    tasks = [(i+1, NUM_ITERATIONS, param_list[i]) for i in range(NUM_ITERATIONS)]

    # 4. Run tasks in parallel
    num_cores = cpu_count()
    print(f"--- Starting {NUM_ITERATIONS} iterations in parallel on {num_cores} cores ---")
    
    # Use initializer to share data without pickling it for every task
    with Pool(processes=num_cores, initializer=init_worker, initargs=(data_1m, data_5m)) as pool:
        results = pool.map(run_backtest_wrapper, tasks)
    
    # 5. Filter out the None results
    good_results = [r for r in results if r is not None]
    
    # 6. Save results to file
    print(f"\n--- Optimization Complete ---")
    print(f"Found {len(good_results)} matching combinations.")
    
    try:
        with open(RESULTS_FILE, 'w') as f:
            json.dump(good_results, f, indent=2)
        print(f"✅ Successfully saved results to {RESULTS_FILE}")
    except Exception as e:
        print(f"❌ Failed to save results: {e}")

if __name__ == "__main__":
    main()
