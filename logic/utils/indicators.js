const { EMA, RSI, ADX, ATR, MACD } = require('technicalindicators');

function calculateIndicators(candles, periodShort = 9, periodLong = 15, rsiPeriod = 14, adxPeriod = 14, atrPeriod = 14) {
    const closes = candles.map(c => c.close);
    const highs = candles.map(c => c.high);
    const lows = candles.map(c => c.low);

    // EMA
    const emaShort = EMA.calculate({ period: periodShort, values: closes });
    const emaLong = EMA.calculate({ period: periodLong, values: closes });

    // RSI
    const rsi = RSI.calculate({ period: rsiPeriod, values: closes });

    // ADX
    const adxInput = {
        high: highs,
        low: lows,
        close: closes,
        period: adxPeriod
    };
    const adx = ADX.calculate(adxInput);

    // ATR
    const atr = ATR.calculate({
        high: highs,
        low: lows,
        close: closes,
        period: atrPeriod
    });

    // MACD
    const macdInput = {
        values: closes,
        fastPeriod: 12,
        slowPeriod: 26,
        signalPeriod: 9,
        SimpleMAOscillator: false,
        SimpleMASignal: false
    };
    const macd = MACD.calculate(macdInput);

    // Align arrays
    // MACD result starts after slowPeriod + signalPeriod - 2 usually, but library returns array.
    // We need to align carefully. The library returns objects {MACD, signal, histogram}
    // The length is input_len - slowPeriod + 1? Let's check offset.
    // MACD calculation usually starts producing values after slowPeriod.
    // Signal line needs signalPeriod more samples.
    // Offset approx slowPeriod + signalPeriod - 2.
    // Let's rely on array length difference.
    
    const macdOffset = closes.length - macd.length;

    const getValue = (arr, i, offset) => {
        const idx = i - offset;
        return idx >= 0 ? arr[idx] : null;
    };

    return candles.map((candle, i) => {
        const m = getValue(macd, i, macdOffset);
        return {
            ...candle,
            ema_short: getValue(emaShort, i, periodShort - 1),
            ema_long: getValue(emaLong, i, periodLong - 1),
            rsi: getValue(rsi, i, rsiPeriod),
            adx: getValue(adx, i, adxPeriod),
            atr: getValue(atr, i, atrPeriod),
            macd: m ? m.MACD : null,
            macd_signal: m ? m.signal : null,
            macd_hist: m ? m.histogram : null
        };
    });
}

module.exports = { calculateIndicators };
