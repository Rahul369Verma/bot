# FILENAME: src/run_optimizer.py
# This is your new high-speed, parallel optimizer.
# Run from your terminal: python src/run_optimizer.py

import os
import sys
import json
import random
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
    'ema_short': (2, 15),
    'ema_long': (16, 50),
    'atr_period': (10, 30),
    'atr_tp_multiplier': (0.5, 5.0),
    'atr_sl_multiplier': (0.2, 2.0),
    'max_trades_per_day': (1, 10),
    'trade_start_time': (dt_time(9, 16), dt_time(12, 0)),
    'trade_end_time': (dt_time(12, 0), dt_time(15, 15)),
}

def random_time(start, end):
    start_ts = int(start.hour * 60 + start.minute)
    end_ts = int(end.hour * 60 + end.minute)
    rand_ts = random.randint(start_ts, end_ts)
    return dt_time(rand_ts // 60, rand_ts % 60)

def generate_random_params():
    """Generates one set of random parameters."""
    rand_params = {
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
    }
    if rand_params['ema_short'] >= rand_params['ema_long']:
        rand_params['ema_long'] = rand_params['ema_short'] + 1
    return rand_params

def run_backtest_wrapper(params_tuple):
    """
    A simple wrapper for multiprocessing.
    It re-initializes the non-picklable Fyers manager
    inside the child process.
    """
    iteration, total_iterations, params, data = params_tuple
    
    try:
        # --- Re-initialize components for this process ---
        # We can't pass the main 'tester' object to a new process
        fyers_manager = FyersDataManager()
        tester = StrategyTester(fyers_manager=fyers_manager)
        
        result = tester.engine.run_backtest(
            strategy_name=STRATEGY_KEY,
            symbol=INDEX_TO_TEST,
            start_date=START_DATE,
            end_date=END_DATE,
            interval="5",
            silent=True, 
            data=data.copy(), # Pass the pre-fetched data
            **params
        )
        
        print(f"  > Iteration {iteration}/{total_iterations}: Sharpe {result.sharpe_ratio:.2f}, WR {result.win_rate:.1f}%, Trades {result.total_trades}")

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

    print(f"Fetching {INDEX_TO_TEST} data from {START_DATE.date()} to {END_DATE.date()}...")
    try:
        data = fyers_manager.get_historical_data(INDEX_TO_TEST, START_DATE, END_DATE, "5", is_backtest_log=True)
        if data is None or data.empty:
            raise Exception("No data returned.")
        print(f"✅ Data fetched successfully ({len(data)} candles).")
    except Exception as e:
        print(f"❌ Failed to fetch data: {e}")
        return

    # 2. Generate all parameter sets
    print(f"Generating {NUM_ITERATIONS} random parameter sets...")
    param_list = [generate_random_params() for _ in range(NUM_ITERATIONS)]
    
    # 3. Create a list of tasks for the pool
    tasks = [(i+1, NUM_ITERATIONS, param_list[i], data) for i in range(NUM_ITERATIONS)]

    # 4. Run tasks in parallel
    num_cores = cpu_count()
    print(f"--- Starting {NUM_ITERATIONS} iterations in parallel on {num_cores} cores ---")
    
    with Pool(processes=num_cores) as pool:
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