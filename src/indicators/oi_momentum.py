# src/indicators/oi_momentum.py
import pandas as pd
import numpy as np

def compute_oi_momentum(df: pd.DataFrame, lookback=3):
    """
    df: DataFrame with columns strike, ce_oi, pe_oi
    We compute delta OI over last snapshots (you must store historical OI snapshots in DB)
    Here we assume df has columns 'ce_oi_prev', 'pe_oi_prev' from prior snapshot.
    """
    df = df.copy()
    df['ce_oi_change_abs'] = df['ce_oi'] - df.get('ce_oi_prev', 0)
    df['pe_oi_change_abs'] = df['pe_oi'] - df.get('pe_oi_prev', 0)
    # ratio or normalized
    df['ce_oi_momentum'] = df['ce_oi_change_abs'] / (df['ce_oi_prev'].replace(0, np.nan)).fillna(1)
    df['pe_oi_momentum'] = df['pe_oi_change_abs'] / (df['pe_oi_prev'].replace(0, np.nan)).fillna(1)
    return df
