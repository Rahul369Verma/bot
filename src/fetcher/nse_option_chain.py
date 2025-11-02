# src/fetcher/nse_option_chain.py
import requests
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime
import time
import json


class NSEOptionChain:
    """
    Fetches real option chain data from NSE India
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
        self.base_url = "https://www.nseindia.com"
        self.cookies = None
        
    def _get_cookies(self):
        """Get required cookies from NSE"""
        try:
            # First request to get cookies
            response = self.session.get(self.base_url, timeout=10)
            self.cookies = response.cookies
            return True
        except Exception as e:
            print(f"Error getting NSE cookies: {e}")
            return False

    def get_option_chain(self, symbol: str = "BANKNIFTY", expiry: str = "") -> List[Dict[str, Any]]:
        """
        Get option chain data from NSE
        """
        try:
            # Ensure we have cookies
            if not self.cookies:
                self._get_cookies()

            # NSE API endpoint for option chain
            url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
            
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_option_chain(data, expiry)
            else:
                print(f"NSE API returned status code: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"Error fetching NSE option chain: {e}")
            return []

    def _parse_option_chain(self, data: Dict, expiry: str = "") -> List[Dict[str, Any]]:
        """Parse NSE option chain response"""
        chain = []
        
        try:
            records = data['records']['data']
            timestamp = data['records']['timestamp']
            underlying_price = data['records']['underlyingValue']
            
            for record in records:
                expiry_date = record.get('expiryDate', '')
                
                # Filter by expiry if provided
                if expiry and expiry_date != expiry:
                    continue
                
                # Parse CE data
                if 'CE' in record:
                    ce_data = record['CE']
                    chain.append({
                        "tradingsymbol": ce_data.get('symbol', ''),
                        "strike": ce_data.get('strikePrice', 0),
                        "type": "CE",
                        "expiry": expiry_date,
                        "ltp": ce_data.get('lastPrice', 0),
                        "oi": ce_data.get('openInterest', 0),
                        "volume": ce_data.get('totalTradedVolume', 0),
                        "change": ce_data.get('change', 0),
                        "iv": ce_data.get('impliedVolatility', 0),
                        "bid_price": ce_data.get('bidprice', 0),
                        "ask_price": ce_data.get('askPrice', 0),
                        "underlying_price": underlying_price
                    })
                
                # Parse PE data
                if 'PE' in record:
                    pe_data = record['PE']
                    chain.append({
                        "tradingsymbol": pe_data.get('symbol', ''),
                        "strike": pe_data.get('strikePrice', 0),
                        "type": "PE",
                        "expiry": expiry_date,
                        "ltp": pe_data.get('lastPrice', 0),
                        "oi": pe_data.get('openInterest', 0),
                        "volume": pe_data.get('totalTradedVolume', 0),
                        "change": pe_data.get('change', 0),
                        "iv": pe_data.get('impliedVolatility', 0),
                        "bid_price": pe_data.get('bidprice', 0),
                        "ask_price": pe_data.get('askPrice', 0),
                        "underlying_price": underlying_price
                    })
            
            return chain
            
        except Exception as e:
            print(f"Error parsing NSE option chain: {e}")
            return []

    def get_expiry_dates(self, symbol: str = "BANKNIFTY") -> List[str]:
        """Get available expiry dates"""
        try:
            url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data['records']['expiryDates']
            else:
                return []
                
        except Exception as e:
            print(f"Error fetching expiry dates: {e}")
            return []


# Alternative fallback using yfinance
def get_option_chain_yfinance(symbol: str = "BANKNIFTY.NS", expiry: str = ""):
    """Fallback using yfinance (limited but reliable)"""
    try:
        import yfinance as yf
        
        # Get the underlying stock/index
        ticker = yf.Ticker(symbol)
        
        # Get options expirations
        expirations = ticker.options
        
        if not expirations:
            return []
            
        # Use nearest expiry if not specified
        if not expiry:
            expiry = expirations[0]
        
        # Get option chain for the expiry
        opt_chain = ticker.option_chain(expiry)
        
        chain = []
        
        # Process calls
        for _, row in opt_chain.calls.iterrows():
            chain.append({
                "tradingsymbol": f"{symbol.replace('.NS', '')}{expiry.replace('-', '')}{int(row['strike'])}{'CE'}",
                "strike": row['strike'],
                "type": "CE",
                "expiry": expiry,
                "ltp": row['lastPrice'],
                "oi": row['openInterest'],
                "volume": 0,  # yfinance doesn't provide volume easily
                "change": 0,
                "iv": row['impliedVolatility'],
                "bid_price": row['bid'],
                "ask_price": row['ask']
            })
        
        # Process puts
        for _, row in opt_chain.puts.iterrows():
            chain.append({
                "tradingsymbol": f"{symbol.replace('.NS', '')}{expiry.replace('-', '')}{int(row['strike'])}{'PE'}",
                "strike": row['strike'],
                "type": "PE",
                "expiry": expiry,
                "ltp": row['lastPrice'],
                "oi": row['openInterest'],
                "volume": 0,
                "change": 0,
                "iv": row['impliedVolatility'],
                "bid_price": row['bid'],
                "ask_price": row['ask']
            })
        
        return chain
        
    except Exception as e:
        print(f"Error with yfinance option chain: {e}")
        return []