# src/fetcher/signal_storage.py
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any
import os


class SignalStorage:
    """
    Store and analyze trading signals for later analysis
    """
    def __init__(self, storage_file="trading_signals.json"):
        self.storage_file = storage_file
        self.signals = self._load_signals()
        
    def _load_signals(self) -> List[Dict[str, Any]]:
        """Load signals from storage file"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading signals: {e}")
        return []
    
    def save_signals(self):
        """Save signals to storage file"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(self.signals, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving signals: {e}")
    
    def add_signal(self, signal: Dict[str, Any]):
        """Add a new signal to storage"""
        # Add timestamp if not present
        if 'storage_timestamp' not in signal:
            signal['storage_timestamp'] = datetime.now().isoformat()
        
        self.signals.append(signal)
        self.save_signals()
    
    def get_recent_signals(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get signals from last N hours"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_signals = []
        for signal in self.signals:
            signal_time = datetime.fromisoformat(signal.get('storage_timestamp', ''))
            if signal_time >= cutoff_time:
                recent_signals.append(signal)
        
        return recent_signals
    
    def get_signals_by_strategy(self, strategy: str) -> List[Dict[str, Any]]:
        """Get signals by strategy type"""
        return [s for s in self.signals if s.get('strategy') == strategy]
    
    def get_executed_signals(self) -> List[Dict[str, Any]]:
        """Get all executed signals"""
        return [s for s in self.signals if s.get('executed')]
    
    def get_signal_analysis(self) -> Dict[str, Any]:
        """Generate analysis of stored signals"""
        if not self.signals:
            return {}
        
        df = pd.DataFrame(self.signals)
        
        # Basic stats
        total_signals = len(self.signals)
        executed_signals = len([s for s in self.signals if s.get('executed')])
        
        # Strategy distribution
        strategy_counts = df['strategy'].value_counts().to_dict()
        
        # Signal type distribution
        signal_type_counts = df['signal'].value_counts().to_dict()
        
        # Confidence analysis
        avg_confidence = df['confidence'].mean() if 'confidence' in df.columns else 0
        
        # Time-based analysis
        df['hour'] = pd.to_datetime(df['storage_timestamp']).dt.hour
        hourly_distribution = df['hour'].value_counts().sort_index().to_dict()
        
        return {
            'total_signals': total_signals,
            'executed_signals': executed_signals,
            'execution_rate': (executed_signals / total_signals * 100) if total_signals > 0 else 0,
            'strategy_distribution': strategy_counts,
            'signal_type_distribution': signal_type_counts,
            'average_confidence': round(avg_confidence, 2),
            'hourly_distribution': hourly_distribution,
            'recent_signals_24h': len(self.get_recent_signals(24))
        }