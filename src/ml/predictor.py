import pandas as pd
import numpy as np
import pandas_ta as ta
from sklearn.neural_network import MLPRegressor, MLPClassifier
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, accuracy_score, classification_report

class PricePredictor:
    def __init__(self):
        self.model = None
        self.trend_model = None # Separate model for Trend Classification
        self.scaler = MinMaxScaler()
        self.trend_scaler = MinMaxScaler()
        self.feature_cols = []
        self.trend_feature_cols = []
        
    def prepare_data(self, df: pd.DataFrame, lookback: int = 5, forecast_horizon: int = 1):
        """
        Prepares data for training/testing (Regressor - 5m base).
        Features: 
        - 5m: Lagged Close, RSI, EMA, Volume, Volume MA
        - 15m: EMA, RSI
        - 1h: EMA, RSI
        Target: Future Close price
        """
        data = df.copy()
        
        # --- 1. Base 5m Indicators ---
        if 'ema_short' not in data.columns:
            data['ema_short'] = data['close'].ewm(span=9, adjust=False).mean()
        if 'rsi' not in data.columns:
            data.ta.rsi(length=14, append=True)
            if 'RSI_14' in data.columns: data.rename(columns={'RSI_14': 'rsi'}, inplace=True)
            
        # Volume MA
        data['vol_ma_20'] = data['volume'].rolling(window=20).mean()
        
        # --- 2. Resample & Calculate Higher Timeframe Indicators ---
        # Resample to 15m
        df_15m = data.resample('15min').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        df_15m['ema_9_15m'] = df_15m['close'].ewm(span=9, adjust=False).mean()
        df_15m.ta.rsi(length=14, append=True)
        if 'RSI_14' in df_15m.columns: df_15m.rename(columns={'RSI_14': 'rsi_15m'}, inplace=True)
        
        # Resample to 1h
        df_1h = data.resample('1h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        df_1h['ema_9_1h'] = df_1h['close'].ewm(span=9, adjust=False).mean()
        df_1h.ta.rsi(length=14, append=True)
        if 'RSI_14' in df_1h.columns: df_1h.rename(columns={'RSI_14': 'rsi_1h'}, inplace=True)
        
        # --- 3. Merge Higher TF Features back to 5m ---
        # We use forward fill to propagate the last known 15m/1h value to the current 5m candle
        data = data.join(df_15m[['ema_9_15m', 'rsi_15m']], how='left')
        data = data.join(df_1h[['ema_9_1h', 'rsi_1h']], how='left')
        
        data.ffill(inplace=True) # Forward fill the higher TF data
        data.dropna(inplace=True)
        
        # --- 4. Create Lagged Features ---
        for i in range(1, lookback + 1):
            data[f'close_lag_{i}'] = data['close'].shift(i)
            data[f'rsi_lag_{i}'] = data['rsi'].shift(i)
            data[f'vol_lag_{i}'] = data['volume'].shift(i)
            
        # Target: Close price 'forecast_horizon' steps ahead
        data['target'] = data['close'].shift(-forecast_horizon)
        
        data.dropna(inplace=True)
        
        # Define Feature Columns
        feature_cols = [c for c in data.columns if 'lag' in c or c in [
            'ema_short', 'rsi', 'vol_ma_20', 
            'ema_9_15m', 'rsi_15m', 
            'ema_9_1h', 'rsi_1h'
        ]]
        self.feature_cols = feature_cols
        
        X = data[feature_cols].values
        y = data['target'].values
        
        return X, y, data.index
        
    def train_model(self, df: pd.DataFrame, lookback: int = 5, epochs: int = 200):
        """
        Trains the MLP Regressor.
        """
        X, y, _ = self.prepare_data(df, lookback=lookback)
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Split data (80% train, 20% test for validation during training)
        X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2, shuffle=False)
        
        # Initialize MLP (Neural Network)
        # Hidden layers: (64, 32) - simple architecture for 5m data
        self.model = MLPRegressor(
            hidden_layer_sizes=(64, 32), 
            activation='relu', 
            solver='adam', 
            max_iter=epochs, 
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1
        )
        
        self.model.fit(X_train, y_train)
        
        train_score = self.model.score(X_train, y_train)
        val_score = self.model.score(X_val, y_val)
        
        return {
            'train_r2': train_score,
            'val_r2': val_score,
            'iterations': self.model.n_iter_,
            'loss': self.model.loss_
        }

    def predict(self, df: pd.DataFrame, lookback: int = 5):
        """
        Generates predictions on the provided dataframe.
        """
        if not self.model:
            raise Exception("Model not trained yet.")
            
        X, y, indices = self.prepare_data(df, lookback=lookback)
        X_scaled = self.scaler.transform(X)
        
        predictions = self.model.predict(X_scaled)
        
        results = pd.DataFrame({
            'Actual': y,
            'Predicted': predictions
        }, index=indices)
        
        # Calculate Metrics
        mse = mean_squared_error(y, predictions)
        mae = mean_absolute_error(y, predictions)
        
        # Directional Accuracy
        results['Actual_Change'] = results['Actual'].diff()
        results['Pred_Change'] = results['Predicted'].diff()
        results.dropna(inplace=True)
        
        correct_direction = np.sign(results['Actual_Change']) == np.sign(results['Pred_Change'])
        dir_acc = accuracy_score(np.ones(len(correct_direction)), correct_direction)
        
        metrics = {
            'MSE': mse,
            'MAE': mae,
            'Directional_Accuracy': dir_acc
        }
        
        return results, metrics

    # --- Trend Model Methods (1H) ---

    def prepare_trend_data(self, df: pd.DataFrame):
        """
        Prepares 1H data for Trend Classification.
        Assumes df is already 1H candles.
        """
        data = df.copy()
        
        # Indicators
        data['ema_9'] = data['close'].ewm(span=9, adjust=False).mean()
        data['ema_21'] = data['close'].ewm(span=21, adjust=False).mean()
        data.ta.rsi(length=14, append=True)
        if 'RSI_14' in data.columns: data.rename(columns={'RSI_14': 'rsi'}, inplace=True)
        
        data['vol_ma_20'] = data['volume'].rolling(window=20).mean()
        
        # Lagged Returns (Momentum)
        data['return_1'] = data['close'].pct_change(1)
        data['return_2'] = data['close'].pct_change(2)
        data['return_3'] = data['close'].pct_change(3)
        
        # Target: 1 if Next Close > Current Close (UP), 0 if Down
        data['target'] = (data['close'].shift(-1) > data['close']).astype(int)
        
        data.dropna(inplace=True)
        
        feature_cols = ['ema_9', 'ema_21', 'rsi', 'vol_ma_20', 'return_1', 'return_2', 'return_3']
        self.trend_feature_cols = feature_cols
        
        X = data[feature_cols].values
        y = data['target'].values
        
        return X, y, data.index

    def train_trend_model(self, df: pd.DataFrame, epochs: int = 200):
        """
        Trains the MLP Classifier for Trend Prediction on 1H data.
        """
        X, y, _ = self.prepare_trend_data(df)
        
        # Scale
        X_scaled = self.trend_scaler.fit_transform(X)
        
        # Split
        X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2, shuffle=False)
        
        # Classifier
        self.trend_model = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation='relu',
            solver='adam',
            max_iter=epochs,
            random_state=42,
            early_stopping=True
        )
        
        self.trend_model.fit(X_train, y_train)
        
        train_acc = self.trend_model.score(X_train, y_train)
        val_acc = self.trend_model.score(X_val, y_val)
        
        return {
            'train_accuracy': train_acc,
            'val_accuracy': val_acc,
            'loss': self.trend_model.loss_
        }

    def predict_trend(self, df: pd.DataFrame):
        """
        Predicts trend (0 or 1) for the provided 1H data.
        """
        if not self.trend_model:
            raise Exception("Trend Model not trained yet.")
            
        X, y, indices = self.prepare_trend_data(df)
        X_scaled = self.trend_scaler.transform(X)
        
        predictions = self.trend_model.predict(X_scaled)
        
        results = pd.DataFrame({
            'Actual': y,
            'Predicted': predictions
        }, index=indices)
        
        accuracy = accuracy_score(y, predictions)
        
        return results, {'accuracy': accuracy}
