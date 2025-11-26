import time
import threading
from typing import Dict, List, Optional, Callable, Any
from fyers_apiv3.FyersWebsocket import data_ws

class FyersSocketManager:
    """
    Manages Fyers WebSocket connection for real-time tick data.
    """
    def __init__(self, access_token: str, log_path: str = None):
        self.access_token = access_token
        self.log_path = log_path or "logs"
        self.fyers_socket = None
        self.ltp_cache: Dict[str, float] = {}
        self.last_update_time: Dict[str, float] = {}
        self.subscribed_symbols: set = set()
        self.lock = threading.Lock()
        self.is_connected = False
        self.stop_event = threading.Event()
        
        # Start the socket connection
        self._start_socket()

    def _start_socket(self):
        """Initializes and starts the Fyers WebSocket."""
        try:
            # Create a FyersDataSocket instance
            # Note: fyers_apiv3.FyersWebsocket.data_ws.FyersDataSocket
            self.fyers_socket = data_ws.FyersDataSocket(
                access_token=self.access_token,
                log_path=self.log_path,
                litemode=True,  # Lite mode for faster, lighter data (LTP only)
                write_to_file=False,
                reconnect=True,
                on_connect=self.on_open,
                on_close=self.on_close,
                on_error=self.on_error,
                on_message=self.on_message
            )
            
            # Connect in a separate thread to avoid blocking
            self.fyers_socket.connect()
            print("✅ Fyers Socket Manager initialized.")
            
        except Exception as e:
            print(f"❌ Error initializing Fyers Socket: {e}")

    def on_open(self):
        """Callback when socket opens."""
        print("✅ Fyers WebSocket Connected.")
        self.is_connected = True
        # Resubscribe if we have symbols pending
        if self.subscribed_symbols:
            print(f"Resubscribing to {len(self.subscribed_symbols)} symbols...")
            self.subscribe(list(self.subscribed_symbols))

    def on_close(self, message=None):
        """Callback when socket closes."""
        print("⚠️ Fyers WebSocket Closed.")
        self.is_connected = False

    def on_error(self, message=None):
        """Callback when error occurs."""
        print(f"❌ Fyers WebSocket Error: {message}")

    def on_message(self, message: Any):
        """
        Callback for tick data.
        Updates the local LTP cache.
        """
        try:
            # Message format depends on litemode.
            # In litemode=True, it's usually a list of dicts or a dict.
            # Example: [{'symbol': 'NSE:NIFTYBANK-INDEX', 'ltp': 43500.0, ...}]
            
            if isinstance(message, list):
                for tick in message:
                    self._process_tick(tick)
            elif isinstance(message, dict):
                self._process_tick(message)
                
        except Exception as e:
            # print(f"Error processing tick: {e}")
            pass

    def _process_tick(self, tick: Dict):
        symbol = tick.get('symbol')
        ltp = tick.get('ltp')
        
        if symbol and ltp:
            with self.lock:
                self.ltp_cache[symbol] = float(ltp)
                self.last_update_time[symbol] = time.time()
                # print(f"Tick: {symbol} -> {ltp}") # Debug (noisy)

    def subscribe(self, symbols: List[str]):
        """
        Subscribes to a list of symbols.
        Args:
            symbols: List of symbols (e.g., ['NSE:NIFTYBANK-INDEX', 'NSE:BANKNIFTY23NOV43500CE'])
        """
        if not symbols: return
        
        # Ensure symbols are in correct format (NSE:...)
        formatted_symbols = []
        for s in symbols:
            if not s.startswith("NSE:") and not s.startswith("MCX:"):
                 formatted_symbols.append(f"NSE:{s}")
            else:
                 formatted_symbols.append(s)
        
        with self.lock:
            self.subscribed_symbols.update(formatted_symbols)
        
        if self.fyers_socket and self.is_connected:
            # Symbol type: 1 for Symbol/LTP? 
            # data_type: SymbolUpdate
            # Fyers V3 subscribe takes symbols list and data_type
            # data_type=1 (DepthUpdate), data_type=2 (SymbolUpdate - LTP, etc)
            try:
                self.fyers_socket.subscribe(symbols=formatted_symbols, data_type="SymbolUpdate")
                print(f"📡 Subscribed to {len(formatted_symbols)} symbols via Socket.")
            except Exception as e:
                print(f"❌ Error subscribing: {e}")

    def unsubscribe(self, symbols: List[str]):
        """Unsubscribes from symbols."""
        if not symbols: return
        
        formatted_symbols = [s if ":" in s else f"NSE:{s}" for s in symbols]
        
        with self.lock:
            self.subscribed_symbols.difference_update(formatted_symbols)
            
            # Clean up cache
            for s in formatted_symbols:
                self.ltp_cache.pop(s, None)
                self.last_update_time.pop(s, None)

        if self.fyers_socket and self.is_connected:
            try:
                self.fyers_socket.unsubscribe(symbols=formatted_symbols)
                print(f"🔕 Unsubscribed from {len(formatted_symbols)} symbols.")
            except Exception as e:
                print(f"❌ Error unsubscribing: {e}")

    def get_ltp(self, symbol: str, max_age_seconds: int = 5) -> Optional[float]:
        """
        Returns the cached LTP if it is fresh enough.
        Returns None if not found or stale.
        """
        if not ":" in symbol:
            symbol = f"NSE:{symbol}"
            
        with self.lock:
            ltp = self.ltp_cache.get(symbol)
            last_time = self.last_update_time.get(symbol)
            
        if ltp is not None and last_time is not None:
            age = time.time() - last_time
            if age <= max_age_seconds:
                return ltp
            else:
                # print(f"⚠️ Socket data stale for {symbol} (Age: {age:.1f}s)")
                pass
                
        return None
