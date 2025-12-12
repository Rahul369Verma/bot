const { EMA, RSI, ADX, ATR } = require("technicalindicators");

class MultiTimeframeStrategy {
    constructor() {
        this.params = {
            ema_short: 9,
            ema_long: 15,
            rsi_period: 14,
            adx_period: 14,
            adx_threshold: 20,
            rsi_overbought: 70,
            rsi_oversold: 30
        };
    }

    calculateIndicators(candles) {
        // candles: [{close, high, low, ...}]
        const closes = candles.map(c => c.close);
        const highs = candles.map(c => c.high);
        const lows = candles.map(c => c.low);

        const emaShort = EMA.calculate({ period: this.params.ema_short, values: closes });
        const emaLong = EMA.calculate({ period: this.params.ema_long, values: closes });
        const rsi = RSI.calculate({ period: this.params.rsi_period, values: closes });
        const adx = ADX.calculate({ period: this.params.adx_period, high: highs, low: lows, close: closes });
        
        // Align arrays (indicators are shorter than input)
        // We return the latest values for live trading
        const lastIdx = closes.length - 1;
        const offset = closes.length - emaShort.length; // EMA offset
        
        return {
            ema_short: emaShort[emaShort.length - 1],
            ema_long: emaLong[emaLong.length - 1],
            prev_ema_short: emaShort[emaShort.length - 2],
            prev_ema_long: emaLong[emaLong.length - 2],
            rsi: rsi[rsi.length - 1],
            adx: adx[adx.length - 1]?.adx
        };
    }

    generateSignal(candles) {
        if (candles.length < 50) return null;

        const ind = this.calculateIndicators(candles);
        const currentPrice = candles[candles.length - 1].close;

        // Crossover Logic
        const bullishCross = (ind.prev_ema_short <= ind.prev_ema_long) && (ind.ema_short > ind.ema_long);
        const bearishCross = (ind.prev_ema_short >= ind.prev_ema_long) && (ind.ema_short < ind.ema_long);

        // Filters
        if (this.params.adx_threshold && ind.adx < this.params.adx_threshold) return null;

        if (bullishCross) {
            if (ind.rsi > this.params.rsi_overbought) return null;
            return { signal: "BUY", type: "CE", price: currentPrice };
        } else if (bearishCross) {
            if (ind.rsi < this.params.rsi_oversold) return null;
            return { signal: "BUY", type: "PE", price: currentPrice };
        }

        return null;
    }
}

module.exports = MultiTimeframeStrategy;
