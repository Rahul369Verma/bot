import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from utils.constants import ALL_STOCKS

def render_ai_prediction_tab(tester):
    """Renders the AI Prediction tab."""
    st.header("🧠 AI Price Prediction (Neural Network)")
    st.markdown("Train a Neural Network (MLP) on 5-minute candle data to predict future price movements.")
    
    ai_col1, ai_col2 = st.columns(2)
    with ai_col1:
        # Combine Indices and Stocks
        available_instruments = ["BANKNIFTY", "NIFTY 50"] + ALL_STOCKS
        ai_symbol = st.selectbox("Select Symbol", available_instruments, index=0, key="ai_symbol")
        ai_lookback = st.slider("Lookback Period (Candles)", 5, 50, 10, help="Number of past candles to use as features.")
    with ai_col2:
        ai_start_date = st.date_input("Training Start Date", datetime.now() - timedelta(days=365), key="ai_start")
        ai_epochs = st.number_input("Training Epochs", 50, 1000, 200, step=50)
        
    # Initialize Session State for AI Results
    if 'ai_results' not in st.session_state:
        st.session_state.ai_results = None
    if 'ai_metrics' not in st.session_state:
        st.session_state.ai_metrics = None
    if 'ai_predictor' not in st.session_state:
        st.session_state.ai_predictor = None

    if st.button("🧠 Train & Predict", type="primary", use_container_width=True):
        st.session_state.ai_training_running = True # Stop auto-refresh
        try:
            from ml.predictor import PricePredictor
            predictor = PricePredictor()
            
            with st.spinner("Fetching Data..."):
                # Convert date to datetime
                ai_start_dt = datetime.combine(ai_start_date, datetime.min.time())
                
                # Always fetch 5m data for AI training as requested
                ai_data = tester.engine.data_manager.get_historical_index_data(
                    ai_symbol, ai_start_dt, datetime.now(), "5", is_backtest_log=True
                )
                
            if ai_data is None or ai_data.empty:
                st.error("No data found for training.")
            else:
                st.info(f"Training on {len(ai_data)} candles...")
                
                # Train
                train_metrics = predictor.train_model(ai_data, lookback=ai_lookback, epochs=ai_epochs)
                
                st.success(f"Training Complete! Loss: {train_metrics['loss']:.4f}, Train R2: {train_metrics['train_r2']:.4f}")
                
                # Predict
                results, metrics = predictor.predict(ai_data, lookback=ai_lookback)
                
                # Store in Session State
                st.session_state.ai_results = results
                st.session_state.ai_metrics = metrics
                st.session_state.ai_predictor = predictor # Store trained model
                
        except ImportError as e:
            st.error(f"Import Error: {e}. Please install missing libraries.")
        except Exception as e:
            st.error(f"An error occurred: {e}")
            import traceback
            st.code(traceback.format_exc())
        finally:
            st.session_state.ai_training_running = False # Re-enable auto-refresh (if needed)

    # Display Results from Session State (Persistent)
    if st.session_state.ai_results is not None and st.session_state.ai_metrics is not None:
        st.markdown("### 📊 Prediction Results")
        
        metrics = st.session_state.ai_metrics
        results = st.session_state.ai_results
        
        # Metrics Display
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("MAE (Error)", f"{metrics['MAE']:.2f}")
        m_col2.metric("RMSE", f"{metrics['MSE']**0.5:.2f}")
        m_col3.metric("Directional Accuracy", f"{metrics['Directional_Accuracy']*100:.1f}%")
        
        # Chart
        st.subheader("Actual vs Predicted Prices")
        st.line_chart(results[['Actual', 'Predicted']].tail(200)) # Show last 200 points
        
        st.divider()
        
        # --- AI Backtest Section ---
        st.subheader("🧪 Backtest AI Strategy")
        if st.button("Run Backtest on Predictions", type="secondary", use_container_width=True):
             if st.session_state.ai_predictor is None:
                 st.error("Model not found. Please train first.")
             else:
                 st.session_state.ai_training_running = True
                 try:
                     with st.spinner("Running Backtest..."):
                         # Get Strategy
                         strategy = tester.engine.strategies['ai_prediction']
                         strategy.set_predictor(st.session_state.ai_predictor)
                         
                         # Run Backtest
                         # Use same data range as training for now (or we could split it)
                         # We need to fetch data again or pass it? 
                         # tester.run_backtest fetches data internally.
                         
                         ai_start_dt = datetime.combine(ai_start_date, datetime.min.time())
                         
                         result = tester.run_backtest(
                             strategy_name='ai_prediction',
                             symbol=ai_symbol,
                             start_date=ai_start_dt,
                             end_date=datetime.now(),
                             interval="5", # AI uses 5m base
                             silent=True,
                             lookback=ai_lookback, # Pass lookback to strategy
                             backtest_mode="Simulated" # Use simulated mode to avoid API limits/errors
                         )
                         
                         if result.total_trades > 0:
                             st.success(f"Backtest Complete! Total Trades: {result.total_trades}")
                             
                             # Display Metrics
                             b_col1, b_col2, b_col3, b_col4 = st.columns(4)
                             b_col1.metric("Total Return", f"{((result.equity_curve.iloc[-1]['equity'] - 100000)/100000)*100:.2f}%")
                             b_col2.metric("Win Rate", f"{result.win_rate:.1f}%")
                             b_col3.metric("Profit Factor", f"{result.profit_factor:.2f}")
                             b_col4.metric("Max Drawdown", f"{result.max_drawdown:.2f}%")
                             
                             # Equity Curve
                             st.line_chart(result.equity_curve['equity'])
                             
                             # Trade Log
                             with st.expander("Trade Log"):
                                 st.dataframe(pd.DataFrame(result.trade_details))
                         else:
                             st.warning("No trades generated during backtest.")
                             
                 except Exception as e:
                     st.error(f"Backtest failed: {e}")
                     import traceback
                     st.code(traceback.format_exc())
                 finally:
                     st.session_state.ai_training_running = False

        if st.button("Clear Results"):
            st.session_state.ai_results = None
            st.session_state.ai_metrics = None
            st.session_state.ai_predictor = None
            st.rerun()

    st.divider()
    
    # --- AI Trend Filter Section ---
    st.header("📉 AI Trend Filter (1H Model)")
    st.markdown("Train a Classifier on 1-hour data to filter backtest signals.")
    
    t_col1, t_col2 = st.columns(2)
    with t_col1:
        trend_start_date = st.date_input("Trend Training Start", datetime(2023, 1, 1), key="trend_start")
    with t_col2:
        trend_end_date = st.date_input("Trend Training End", datetime(2024, 12, 31), key="trend_end")
        
    if st.button("Train Trend Model", type="primary"):
        st.session_state.ai_training_running = True
        try:
            from ml.predictor import PricePredictor
            # Use existing predictor or create new
            if st.session_state.ai_predictor is None:
                predictor = PricePredictor()
            else:
                predictor = st.session_state.ai_predictor
                
            with st.spinner("Fetching 1H Data for Trend Model..."):
                trend_start_dt = datetime.combine(trend_start_date, datetime.min.time())
                trend_end_dt = datetime.combine(trend_end_date, datetime.max.time())
                
                # Fetch 1H data
                trend_data = tester.engine.data_manager.get_historical_index_data(
                    ai_symbol, trend_start_dt, trend_end_dt, "60", is_backtest_log=True
                )
                
            if trend_data is None or trend_data.empty:
                st.error("No 1H data found for training.")
            else:
                st.info(f"Training Trend Model on {len(trend_data)} 1H candles...")
                metrics = predictor.train_trend_model(trend_data, epochs=200)
                
                st.success(f"Trend Model Trained! Accuracy: {metrics['train_accuracy']:.2f} (Train) / {metrics['val_accuracy']:.2f} (Val)")
                st.session_state.ai_predictor = predictor
                
        except Exception as e:
            st.error(f"Trend Training failed: {e}")
        finally:
            st.session_state.ai_training_running = False
