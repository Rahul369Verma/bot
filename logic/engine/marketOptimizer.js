const BacktestEngine = require('./backtestEngine');
const FyersDataManager = require("../fetcher/fyersData");
const { calculateIndicators } = require("../utils/indicators");
const { getFyersSymbol } = require("../utils/symbols");

class MarketOptimizer {
    constructor() {
        this.fyersManager = new FyersDataManager();
        this.backtestEngine = new BacktestEngine();
    }

    async analyze(symbol, params = {}) {
        try {
            // Check if we should run optimization (Genetic Algorithm)
            if (params.iterations && params.iterations > 0) {
                return await this.runOptimization(symbol, params);
            }

            // Default: Single Analysis (Current Market State)
            const timeframes = ["5", "15", "60"];
            const results = {};
            const now = new Date();
            const toDate = now.toISOString().split('T')[0];
            const fromDate = new Date(now.getTime() - 10 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]; // Last 10 days

            let overallScore = 0; // -3 to +3 (Bearish to Bullish)

            for (const tf of timeframes) {
                // Fetch Data
                const candles = await this.fyersManager.getHistory(symbol, tf, fromDate, toDate);
                if (!candles || candles.length < 50) {
                    results[tf] = { error: "Insufficient Data" };
                    continue;
                }

                // Calculate Indicators
                const processed = calculateIndicators(candles);
                const last = processed[processed.length - 1];
                const prev = processed[processed.length - 2];

                if (!last) {
                    results[tf] = { error: "Calculation Failed" };
                    continue;
                }

                // Analysis
                const analysis = {
                    trend: "NEUTRAL",
                    rsi_status: "NEUTRAL",
                    macd_signal: "NEUTRAL",
                    score: 0
                };

                // 1. EMA Trend
                if (last.ema_short > last.ema_long) {
                    analysis.trend = "BULLISH";
                    analysis.score += 1;
                } else if (last.ema_short < last.ema_long) {
                    analysis.trend = "BEARISH";
                    analysis.score -= 1;
                }

                // 2. RSI
                if (last.rsi > 70) {
                    analysis.rsi_status = "OVERBOUGHT";
                    analysis.score -= 0.5; // Potential reversal
                } else if (last.rsi < 30) {
                    analysis.rsi_status = "OVERSOLD";
                    analysis.score += 0.5; // Potential reversal
                } else if (last.rsi > 50) {
                    analysis.rsi_status = "BULLISH_ZONE";
                    analysis.score += 0.5;
                } else {
                    analysis.rsi_status = "BEARISH_ZONE";
                    analysis.score -= 0.5;
                }

                // 3. MACD
                if (last.macd > last.macd_signal) {
                    analysis.macd_signal = "BULLISH";
                    analysis.score += 1;
                    // Check for crossover
                    if (prev.macd <= prev.macd_signal) {
                        analysis.macd_signal = "BULLISH_CROSSOVER";
                        analysis.score += 1; // Stronger signal
                    }
                } else {
                    analysis.macd_signal = "BEARISH";
                    analysis.score -= 1;
                    if (prev.macd >= prev.macd_signal) {
                        analysis.macd_signal = "BEARISH_CROSSOVER";
                        analysis.score -= 1;
                    }
                }

                results[tf] = {
                    data: {
                        close: last.close,
                        rsi: last.rsi.toFixed(2),
                        macd: last.macd.toFixed(2),
                        ema_9: last.ema_short.toFixed(2),
                        ema_15: last.ema_long.toFixed(2)
                    },
                    analysis: analysis
                };

                overallScore += analysis.score;
            }

            // Final Prediction
            let prediction = "NEUTRAL";
            if (overallScore >= 4) prediction = "STRONG_BUY";
            else if (overallScore >= 2) prediction = "BUY";
            else if (overallScore <= -4) prediction = "STRONG_SELL";
            else if (overallScore <= -2) prediction = "SELL";

            return {
                symbol: symbol,
                timestamp: new Date().toISOString(),
                prediction: prediction,
                overall_score: overallScore,
                details: results
            };

        } catch (err) {
            console.error("❌ Optimizer Analysis Error:", err);
            return { error: err.message };
        }
    }

    async runOptimization(symbol, params) {
        const iterations = params.iterations || 10;
        const startDate = params.start_date;
        const endDate = params.end_date;
        const capital = parseFloat(params.capital) || 100000;
        
        if (!startDate || !endDate) return { error: "Start Date and End Date are required" };
        
        const fyersSymbol = getFyersSymbol(symbol);
        
        console.log(`🧬 Running Genetic Optimization for ${symbol} from ${startDate} to ${endDate} with ${iterations} iterations...`);
        
        // 1. Fetch Data Once (Optimization: Don't refetch for every iteration)
        const data5m = await this.backtestEngine.fetchData(fyersSymbol, startDate, endDate, "5");
        const data15m = await this.backtestEngine.fetchData(fyersSymbol, startDate, endDate, "15");
        const data60m = await this.backtestEngine.fetchData(fyersSymbol, startDate, endDate, "60");
        
        if (!data5m.length) return { error: "Insufficient Data for Optimization" };
        
        const results = [];
        
        for (let i = 0; i < iterations; i++) {
            // Generate Random Params
            const p = this.generateRandomParams();
            
            // Calculate Indicators with these params
            // Note: calculateIndicators signature: (candles, periodShort, periodLong, rsiPeriod, adxPeriod, atrPeriod)
            const processed5m = calculateIndicators(data5m, p.ema_short, p.ema_long, p.rsi_period, p.adx_period, p.atr_period);
            const processed15m = calculateIndicators(data15m, p.ema_short, p.ema_long, p.rsi_period, p.adx_period, p.atr_period);
            const processed60m = calculateIndicators(data60m, p.ema_short, p.ema_long, p.rsi_period, p.adx_period, p.atr_period);
            
            // Align Trends
            const aligned = this.backtestEngine.alignTrends(processed5m, processed15m, processed60m);
            
            // Run Strategy
            const res = this.backtestEngine.runMTAStrategy(aligned, capital, p);
            
            // Calculate Metrics
            const totalTrades = res.trades.length;
            const winningTrades = res.trades.filter(t => t.pnl > 0).length;
            const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
            const totalPnL = res.finalBalance - capital;
            
            // Calculate Max Drawdown
            let maxPeak = -Infinity;
            let maxDrawdown = 0;
            res.equityCurve.forEach(pt => {
                if (pt.balance > maxPeak) maxPeak = pt.balance;
                const dd = (maxPeak - pt.balance) / maxPeak * 100;
                if (dd > maxDrawdown) maxDrawdown = dd;
            });

            // Filter Results
            const minTrades = params.min_trades !== undefined ? params.min_trades : 5;
            const minWinRate = params.min_win_rate !== undefined ? params.min_win_rate : 40;
            const maxAllowedDrawdown = params.max_drawdown !== undefined ? params.max_drawdown : 100;

            if (totalTrades >= minTrades && winRate >= minWinRate && maxDrawdown <= maxAllowedDrawdown) {
                results.push({
                    params: p,
                    metrics: {
                        totalTrades,
                        winRate: parseFloat(winRate.toFixed(2)),
                        totalPnL: parseFloat(totalPnL.toFixed(2)),
                        finalBalance: parseFloat(res.finalBalance.toFixed(2)),
                        maxDrawdown: parseFloat(maxDrawdown.toFixed(2))
                    }
                });
            } else {
                console.log(`❌ Rejected: Trades=${totalTrades}, WinRate=${winRate}, DD=${maxDrawdown}`);
            }
        }
        
        // Sort by PnL (Descending)
        results.sort((a, b) => b.metrics.totalPnL - a.metrics.totalPnL);
        
        return {
            type: "optimization_result",
            symbol,
            best_parameters: results.slice(0, 5), // Top 5
            all_results_count: results.length,
            timestamp: new Date().toISOString()
        };
    }

    generateRandomParams() {
        const randInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
        
        const ema_short = randInt(5, 20);
        return {
            ema_short: ema_short,
            ema_long: randInt(ema_short + 2, 50), // Ensure long > short
            adx_threshold: randInt(15, 30),
            rsi_overbought: randInt(65, 85),
            rsi_oversold: randInt(15, 35),
            use_adx_filter: Math.random() > 0.3, // 70% chance to use
            use_rsi_filter: Math.random() > 0.3,
            use_15m_filter: true, // Keep core filters mostly on
            use_1h_filter: Math.random() > 0.5,
            atr_tp_mult: (Math.random() * 3 + 2).toFixed(1), // 2.0 - 5.0
            atr_sl_mult: (Math.random() * 1 + 1).toFixed(1),  // 1.0 - 2.0
            lot_size: 35,
            // Explicitly define fixed params to ensure Backtest uses same values
            rsi_period: 14,
            adx_period: 14,
            atr_period: 14,
            trade_start_time: "09:30",
            trade_end_time: "15:00",
            max_daily_loss: 2000,
            max_trades_per_day: 10
        };
    }
}

module.exports = MarketOptimizer;
