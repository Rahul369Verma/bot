import pandas as pd
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from ml.predictor import PricePredictor
    print("Successfully imported PricePredictor")
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def test_predictor():
    print("Creating dummy data...")
    dates = pd.date_range(start='2024-01-01', periods=1000, freq='5min')
    df = pd.DataFrame({
        'open': np.random.rand(1000) * 100,
        'high': np.random.rand(1000) * 100,
        'low': np.random.rand(1000) * 100,
        'close': np.random.rand(1000) * 100,
        'volume': np.random.randint(1, 100, 1000)
    }, index=dates)
    
    print("Initializing Predictor...")
    predictor = PricePredictor()
    
    print("Training model...")
    try:
        metrics = predictor.train_model(df, lookback=10, epochs=50)
        print("Training complete.")
        print("Metrics:", metrics)
        
        # Verify new features
        print("Verifying features...")
        print(f"Feature Cols: {predictor.feature_cols}")
        expected_features = ['ema_9_15m', 'rsi_15m', 'ema_9_1h', 'rsi_1h', 'vol_ma_20']
        for feat in expected_features:
            if feat in predictor.feature_cols:
                print(f"✅ Found feature: {feat}")
            else:
                print(f"❌ Missing feature: {feat}")
    except Exception as e:
        print(f"Training failed: {e}")
        import traceback
        traceback.print_exc()
        return

    print("Predicting...")
    try:
        results, metrics = predictor.predict(df, lookback=10)
        print("Prediction complete.")
        print("Prediction Metrics:", metrics)
    except Exception as e:
        print(f"Prediction failed: {e}")
        import traceback
        traceback.print_exc()

    # --- Trend Model Verification ---
    print("\n--- Verifying Trend Model (1H) ---")
    print("Creating dummy 1H data...")
    dates_1h = pd.date_range(start='2024-01-01', periods=500, freq='1h')
    df_1h = pd.DataFrame({
        'open': np.random.rand(500) * 100,
        'high': np.random.rand(500) * 100,
        'low': np.random.rand(500) * 100,
        'close': np.random.rand(500) * 100,
        'volume': np.random.randint(1, 100, 500)
    }, index=dates_1h)
    
    print("Training Trend Model...")
    try:
        trend_metrics = predictor.train_trend_model(df_1h, epochs=50)
        print("Trend Training complete.")
        print("Trend Metrics:", trend_metrics)
        
        print("Predicting Trend...")
        trend_results, trend_acc = predictor.predict_trend(df_1h)
        print("Trend Prediction complete.")
        print("Trend Accuracy:", trend_acc)
        print("Predictions head:", trend_results['Predicted'].head().values)
        
        if set(trend_results['Predicted'].unique()).issubset({0, 1}):
            print("✅ Trend predictions are binary (0/1).")
        else:
            print("❌ Trend predictions are NOT binary.")
            
    except Exception as e:
        print(f"Trend Model failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_predictor()
