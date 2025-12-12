const FyersDataManager = require('../fetcher/fyersData');
const { calculateIndicators } = require('../utils/indicators');
const { getFyersSymbol } = require('../utils/symbols');

class BacktestEngine {
    constructor() {
        this.fyersManager = new FyersDataManager();
    }

    // Helper: Fetch Data for a specific timeframe
    async fetchData(symbol, startDate, endDate, resolution) {
        // Fyers API expects date format: YYYY-MM-DD
        // resolution: "5", "15", "60"
        try {
            console.log(`📥 Fetching ${resolution}m data for ${symbol}...`);
            const data = await this.fyersManager.getHistory(symbol, resolution, startDate, endDate);
            // data format from fyersData.js: [{ date, open, high, low, close, volume }, ...]
            return data || [];
        } catch (err) {
            console.error(`❌ Error fetching ${resolution}m data:`, err.message);
            return [];
        }
    }

    // Helper: Calculate Indicators (Delegated to Utility)
    calculateIndicators(candles, periodShort = 9, periodLong = 15, rsiPeriod = 14, adxPeriod = 14, atrPeriod = 14) {
        return calculateIndicators(candles, periodShort, periodLong, rsiPeriod, adxPeriod, atrPeriod);
    }

    // Helper: Resample/Align Higher Timeframe Trend
    alignTrends(baseCandles, tf15Candles, tf60Candles) {
        // Sort to ensure chronological order
        tf15Candles.sort((a, b) => new Date(a.date) - new Date(b.date));
        tf60Candles.sort((a, b) => new Date(a.date) - new Date(b.date));

        let ptr15 = 0;
        let ptr60 = 0;

        return baseCandles.map(c => {
            const time = new Date(c.date).getTime();

            // Advance ptr15 to the latest candle that has CLOSED at or before current time
            // 15m candle at T opens at T and closes at T+15m. 
            // We can only use it if T+15m <= current time.
            while (ptr15 < tf15Candles.length - 1 && new Date(tf15Candles[ptr15 + 1].date).getTime() + 15 * 60 * 1000 <= time) {
                ptr15++;
            }
            
            // Advance ptr60 to the latest candle that has CLOSED at or before current time
            while (ptr60 < tf60Candles.length - 1 && new Date(tf60Candles[ptr60 + 1].date).getTime() + 60 * 60 * 1000 <= time) {
                ptr60++;
            }

            let c15 = tf15Candles[ptr15];
            // If the selected candle hasn't closed yet relative to current time, don't use it
            if (c15 && new Date(c15.date).getTime() + 15 * 60 * 1000 > time) c15 = null;

            let c60 = tf60Candles[ptr60];
            if (c60 && new Date(c60.date).getTime() + 60 * 60 * 1000 > time) c60 = null;

            // Determine trends based on the latest available higher-tf candle
            // We check if the candle is valid and not "too far" in the past? 
            // Python uses ffill(), effectively using the last known value indefinitely. We will do the same.
            
            const trend15 = (c15 && c15.ema_short && c15.ema_long) 
                ? (c15.ema_short > c15.ema_long ? 'BULLISH' : 'BEARISH') 
                : 'NEUTRAL';

            const trend60 = (c60 && c60.ema_short && c60.ema_long)
                ? (c60.ema_short > c60.ema_long ? 'BULLISH' : 'BEARISH')
                : 'NEUTRAL';

            return {
                ...c,
                trend15,
                trend60
            };
        });
    }

    async run(symbol, startDate, endDate, capital = 100000, strategyName = 'mta_ema_crossover', params = {}) {
        const fyersSymbol = getFyersSymbol(symbol);
        capital = parseFloat(capital); // Ensure capital is a number
        console.log(`🚀 Starting Backtest for ${symbol} (${fyersSymbol}) from ${startDate} to ${endDate} using ${strategyName}`);
        console.log("   Params:", params);

        // 1. Fetch Data
        const data5m = await this.fetchData(fyersSymbol, startDate, endDate, "5");
        
        if (data5m.length === 0) return { error: "No data found for 5m timeframe" };

        // 2. Strategy Selection
        let trades = [];
        let equityCurve = [];
        let balance = capital;

        if (strategyName === 'mta_ema_crossover') {
            const data15m = await this.fetchData(fyersSymbol, startDate, endDate, "15");
            const data60m = await this.fetchData(fyersSymbol, startDate, endDate, "60");

            const emaShort = parseInt(params.ema_short) || 9;
            const emaLong = parseInt(params.ema_long) || 15;
            const rsiPeriod = parseInt(params.rsi_period) || 14;
            const adxPeriod = parseInt(params.adx_period) || 14;
            const atrPeriod = parseInt(params.atr_period) || 14;

            const processed5m = this.calculateIndicators(data5m, emaShort, emaLong, rsiPeriod, adxPeriod, atrPeriod);
            const processed15m = this.calculateIndicators(data15m, emaShort, emaLong, rsiPeriod, adxPeriod, atrPeriod);
            const processed60m = this.calculateIndicators(data60m, emaShort, emaLong, rsiPeriod, adxPeriod, atrPeriod);

            const alignedData = this.alignTrends(processed5m, processed15m, processed60m);
            const result = this.runMTAStrategy(alignedData, capital, params);
            trades = result.trades;
            equityCurve = result.equityCurve;
            balance = result.finalBalance;
        } 
        else if (strategyName === 'ema_daily_trend') {
            // Placeholder for EMA Daily Trend
            console.log("⚠️ Strategy 'ema_daily_trend' is a placeholder.");
            return { error: "Strategy implementation pending." };
        }
        else {
             console.log(`⚠️ Unknown strategy: ${strategyName}`);
             return { error: `Unknown strategy: ${strategyName}` };
        }

        // ... (Metrics calculation remains same) ...
        
        // 5. Metrics
        const totalTrades = trades.length;
        const winningTrades = trades.filter(t => t.pnl > 0).length;
        const losingTrades = trades.filter(t => t.pnl <= 0).length;
        const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
        const totalPnL = balance - capital;
        
        // Max Drawdown
        let maxPeak = -Infinity;
        let maxDrawdown = 0;
        equityCurve.forEach(pt => {
            if (pt.balance > maxPeak) maxPeak = pt.balance;
            const dd = (maxPeak - pt.balance) / maxPeak * 100;
            if (dd > maxDrawdown) maxDrawdown = dd;
        });

        return {
            metrics: {
                totalTrades,
                winningTrades,
                losingTrades,
                winRate: parseFloat(winRate.toFixed(2)),
                totalPnL: parseFloat(totalPnL.toFixed(2)),
                finalBalance: parseFloat(balance.toFixed(2)),
                maxDrawdown: parseFloat(maxDrawdown.toFixed(2))
            },
            trades: trades.reverse(),
            equityCurve
        };
    }

    // Extracted MTA Logic
    runMTAStrategy(alignedData, capital, params) {
        let position = null;
        const trades = [];
        let balance = capital;
        const lotSize = parseInt(params.lot_size) || 35; 
        const equityCurve = [];

        // Parse Params
        const useAdx = params.use_adx_filter === 'true' || params.use_adx_filter === true;
        const adxThreshold = parseInt(params.adx_threshold) || 20;
        const useRsi = params.use_rsi_filter === 'true' || params.use_rsi_filter === true;
        const rsiOverbought = parseInt(params.rsi_overbought) || 70;
        const rsiOversold = parseInt(params.rsi_oversold) || 30;
        
        // Timeframe Filters (Default to Python defaults: 15m=True, 1h=False)
        const use15mFilter = params.use_15m_filter !== 'false' && params.use_15m_filter !== false; // Default true
        const use1hFilter = params.use_1h_filter === 'true' || params.use_1h_filter === true; // Default false

        // Risk & Time Params
        const maxDailyLoss = parseInt(params.max_daily_loss) || 2000;
        const maxTradesPerDay = parseInt(params.max_trades_per_day) || 10;
        const startTimeStr = params.trade_start_time || "09:30";
        const endTimeStr = params.trade_end_time || "15:00";
        
        // ATR Params
        const atrTpMult = parseFloat(params.atr_tp_mult) || 4.3;
        const atrSlMult = parseFloat(params.atr_sl_mult) || 1.4;

        // Helper: Time Check
        const isTimeInRange = (date) => {
            const hours = date.getHours();
            const minutes = date.getMinutes();
            const timeVal = hours * 60 + minutes;
            
            const [startH, startM] = startTimeStr.split(':').map(Number);
            const startVal = startH * 60 + startM;
            
            const [endH, endM] = endTimeStr.split(':').map(Number);
            const endVal = endH * 60 + endM;

            return timeVal >= startVal && timeVal <= endVal;
        };

        // Daily Tracking
        let currentDay = null;
        let dailyPnL = 0;
        let dailyTrades = 0;

        console.log(`🔍 Processing ${alignedData.length} aligned candles...`);
        console.log(`   Filters: 15m=${use15mFilter}, 1h=${use1hFilter}, ADX=${useAdx}, RSI=${useRsi}`);

        for (let i = 1; i < alignedData.length; i++) {
            const candle = alignedData[i];
            const prevCandle = alignedData[i - 1];
            const candleDate = new Date(candle.date);
            const dayStr = candleDate.toDateString();

            // Reset Daily Stats on new day
            if (dayStr !== currentDay) {
                currentDay = dayStr;
                dailyPnL = 0;
                dailyTrades = 0;
            }

            if (!candle.ema_short || !candle.ema_long || !candle.adx || !candle.adx.adx || !candle.atr || candle.rsi == null) continue;

            // Check Risk Limits
            if (dailyPnL <= -maxDailyLoss) continue; // Stop trading for the day
            if (dailyTrades >= maxTradesPerDay) continue;

            const adxValue = candle.adx.adx;
            const rsiValue = candle.rsi;
            const atrValue = candle.atr;

            // Strategy Signals
            const isCrossoverBuy = prevCandle.ema_short <= prevCandle.ema_long && candle.ema_short > candle.ema_long;
            const isCrossoverSell = prevCandle.ema_short >= prevCandle.ema_long && candle.ema_short < candle.ema_long;
            
            // Trend Alignment Logic
            let isTrendBullish = true;
            let isTrendBearish = true;

            if (use15mFilter) {
                isTrendBullish = isTrendBullish && (candle.trend15 === 'BULLISH');
                isTrendBearish = isTrendBearish && (candle.trend15 === 'BEARISH');
            }
            
            if (use1hFilter) {
                isTrendBullish = isTrendBullish && (candle.trend60 === 'BULLISH');
                isTrendBearish = isTrendBearish && (candle.trend60 === 'BEARISH');
            }

            // Debug Log for first few candles or when crossover happens
            // if (i < 5 || isCrossoverBuy || isCrossoverSell) {
            //     console.log(`🕯️ Candle ${i} (${candle.date}): Close=${candle.close}, EMA_S=${candle.ema_short.toFixed(2)}, EMA_L=${candle.ema_long.toFixed(2)}, ADX=${adxValue.toFixed(2)}, RSI=${rsiValue.toFixed(2)}, Trend15=${candle.trend15}, Trend60=${candle.trend60}`);
            //     if (isCrossoverBuy) console.log(`   🚀 Buy Signal Check: TrendBull=${isTrendBullish}, ADX>${adxThreshold}=${!useAdx || adxValue > adxThreshold}, RSI<${rsiOverbought}=${!useRsi || rsiValue < rsiOverbought}`);
            //     if (isCrossoverSell) console.log(`   🔻 Sell Signal Check: TrendBear=${isTrendBearish}, ADX>${adxThreshold}=${!useAdx || adxValue > adxThreshold}, RSI>${rsiOversold}=${!useRsi || rsiValue > rsiOversold}`);
            // }

            // Filter Checks
            let isAdxOk = true;
            if (useAdx) isAdxOk = adxValue > adxThreshold;

            let isRsiBuyOk = true;
            let isRsiSellOk = true;
            if (useRsi) {
                isRsiBuyOk = rsiValue < rsiOverbought;
                isRsiSellOk = rsiValue > rsiOversold;
            }

            // Entry Logic
            if (!position) {
                if (isTimeInRange(candleDate)) {
                    if (isCrossoverBuy && isTrendBullish && isAdxOk && isRsiBuyOk) {
                        // Calculate SL/TP based on ATR (Simulated Option Premium via 0.5 Delta)
                        // Option Move ~ 0.5 * Index Move
                        // Target Option Points = ATR * TpMult * 0.5
                        // SL Option Points = ATR * SlMult * 0.5
                        const slPoints = atrValue * atrSlMult * 0.5;
                        const tpPoints = atrValue * atrTpMult * 0.5;

                        position = { 
                            type: 'BUY', 
                            entryPrice: candle.close, // Spot Price
                            entryTime: candle.date, 
                            quantity: lotSize,
                            slPoints: slPoints,
                            tpPoints: tpPoints
                        };
                    } else if (isCrossoverSell && isTrendBearish && isAdxOk && isRsiSellOk) {
                        const slPoints = atrValue * atrSlMult * 0.5;
                        const tpPoints = atrValue * atrTpMult * 0.5;

                        position = { 
                            type: 'SELL', 
                            entryPrice: candle.close, 
                            entryTime: candle.date, 
                            quantity: lotSize,
                            slPoints: slPoints,
                            tpPoints: tpPoints
                        };
                    }
                }
            } 
            // Exit Logic
            else {
                let exitPrice = null;
                let reason = '';

                // Calculate Simulated Option PnL (Per Unit)
                // For Buy Call: (CurrentSpot - EntrySpot) * 0.5
                // For Buy Put (Sell Signal): (EntrySpot - CurrentSpot) * 0.5
                let currentPnLPoints = 0;
                if (position.type === 'BUY') {
                    currentPnLPoints = (candle.close - position.entryPrice) * 0.5;
                } else {
                    currentPnLPoints = (position.entryPrice - candle.close) * 0.5;
                }

                // Check SL/TP
                if (currentPnLPoints <= -position.slPoints) {
                    exitPrice = candle.close; reason = 'SL Hit';
                } else if (currentPnLPoints >= position.tpPoints) {
                    exitPrice = candle.close; reason = 'TP Hit';
                }
                // Reverse Signal Exit
                else if (position.type === 'BUY' && candle.ema_short < candle.ema_long) {
                    exitPrice = candle.close; reason = 'Crossover Exit';
                } else if (position.type === 'SELL' && candle.ema_short > candle.ema_long) {
                    exitPrice = candle.close; reason = 'Crossover Exit';
                }
                // Time Exit (End of Day)
                else if (!isTimeInRange(candleDate)) {
                    exitPrice = candle.close; reason = 'Time Exit';
                }

                if (exitPrice) {
                    // Recalculate Final PnL
                    let finalPnLPoints = 0;
                    if (position.type === 'BUY') {
                        finalPnLPoints = (exitPrice - position.entryPrice) * 0.5;
                    } else {
                        finalPnLPoints = (position.entryPrice - exitPrice) * 0.5;
                    }

                    // Apply SL/TP limits strictly if hit (slippage ignored for now)
                    if (reason === 'SL Hit') finalPnLPoints = -position.slPoints;
                    if (reason === 'TP Hit') finalPnLPoints = position.tpPoints;

                    const pnl = finalPnLPoints * position.quantity;
                    balance += pnl;
                    dailyPnL += pnl;
                    dailyTrades++;

                    trades.push({
                        entryTime: position.entryTime, exitTime: candle.date, type: position.type,
                        entryPrice: position.entryPrice, exitPrice: exitPrice, quantity: position.quantity,
                        pnl: parseFloat(pnl.toFixed(2)), reason: reason
                    });
                    position = null;
                }
            }
            equityCurve.push({ date: candle.date, balance: parseFloat(balance.toFixed(2)) });
        }
        return { trades, equityCurve, finalBalance: balance };
    }
}

module.exports = BacktestEngine;
