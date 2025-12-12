require('dotenv').config({ path: '../.env' });
const MarketOptimizer = require('./logic/engine/marketOptimizer');
const BacktestEngine = require('./logic/engine/backtestEngine');

async function debugConsistency() {
    const optimizer = new MarketOptimizer();
    const backtestEngine = new BacktestEngine();

    const symbol = "BANKNIFTY";
    const params = {
        start_date: "2024-01-01",
        end_date: "2024-01-10",
        capital: 100000,
        iterations: 1, // Run 1 iteration
        min_trades: 0,
        min_win_rate: 0,
        max_drawdown: 100
    };

    console.log("--- 1. Running Optimizer ---");
    // Mock generateRandomParams to return a FIXED set of params for deterministic testing
    optimizer.generateRandomParams = () => {
        return {
            ema_short: 9,
            ema_long: 21,
            adx_threshold: 20,
            rsi_overbought: 70,
            rsi_oversold: 30,
            use_adx_filter: true,
            use_rsi_filter: true,
            use_15m_filter: true,
            use_1h_filter: false,
            atr_tp_mult: 3.0,
            atr_sl_mult: 1.5,
            lot_size: 35,
            rsi_period: 14,
            adx_period: 14,
            atr_period: 14,
            trade_start_time: "09:30",
            trade_end_time: "15:00",
            max_daily_loss: 2000,
            max_trades_per_day: 10
        };
    };

    const optResult = await optimizer.runOptimization(symbol, params);
    
    if (!optResult.best_parameters || optResult.best_parameters.length === 0) {
        console.error("❌ Optimizer returned no results!");
        return;
    }

    const best = optResult.best_parameters[0];
    console.log("Optimizer Result:", JSON.stringify(best.metrics, null, 2));
    console.log("Params:", JSON.stringify(best.params, null, 2));

    console.log("\n--- 2. Running Backtest with SAME Params ---");
    // Construct backtest params (simulating what frontend sends)
    const backtestParams = {
        symbol: symbol,
        start_date: params.start_date,
        end_date: params.end_date,
        capital: params.capital,
        ...best.params // Spread the params from optimizer
    };

    // Note: BacktestEngine.run expects (symbol, start, end, capital, strategyName, params)
    const btResult = await backtestEngine.run(
        symbol, 
        params.start_date, 
        params.end_date, 
        params.capital, 
        'mta_ema_crossover', 
        backtestParams
    );

    console.log("Backtest Result:", JSON.stringify(btResult.metrics, null, 2));

    console.log("\n--- 3. Comparison ---");
    const optPnL = best.metrics.totalPnL;
    const btPnL = btResult.metrics.totalPnL;
    const optTrades = best.metrics.totalTrades;
    const btTrades = btResult.metrics.totalTrades;

    if (optPnL === btPnL && optTrades === btTrades) {
        console.log("✅ MATCH: Results are identical.");
    } else {
        console.log("❌ MISMATCH: Results differ.");
        console.log(`PnL: Opt=${optPnL}, BT=${btPnL}`);
        console.log(`Trades: Opt=${optTrades}, BT=${btTrades}`);
    }
    
    process.exit(0);
}

debugConsistency();
