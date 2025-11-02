# src/data/option_parser.py
import pandas as pd
from typing import Dict, Any

def parse_option_chain(raw_chain: dict) -> pd.DataFrame:
    """
    Convert raw option-chain JSON into DataFrame with columns:
    strike, ce_oi, ce_oi_change, ce_ltp, pe_oi, pe_oi_change, pe_ltp, etc.
    raw_chain is expected in NSE-like shape.
    """
    rows = []
    for strike, data in raw_chain.items():
        # Example mapping — adjust to the real API output you use.
        rows.append({
            "strike": strike,
            "ce_oi": data.get("CE", {}).get("openInterest", 0),
            "ce_oi_change": data.get("CE", {}).get("changeinOpenInterest", 0),
            "ce_ltp": data.get("CE", {}).get("lastPrice", 0),
            "pe_oi": data.get("PE", {}).get("openInterest", 0),
            "pe_oi_change": data.get("PE", {}).get("changeinOpenInterest", 0),
            "pe_ltp": data.get("PE", {}).get("lastPrice", 0),
        })
    df = pd.DataFrame(rows).sort_values("strike")
    return df
