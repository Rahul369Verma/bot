const getNextExpiry = () => {
    const today = new Date();
    
    // Helper to get last Wednesday of a month
    const getLastWednesday = (year, month) => {
        const date = new Date(year, month + 1, 0); // Last day of month
        const day = date.getDay(); // 0=Sun, ... 3=Wed
        const diff = (day - 3 + 7) % 7;
        date.setDate(date.getDate() - diff);
        return date;
    };

    let expiry = getLastWednesday(today.getFullYear(), today.getMonth());

    // If today is past the expiry (or it's today after 3:30 PM), move to next month
    if (today > expiry || (today.getDate() === expiry.getDate() && today.getHours() >= 15 && today.getMinutes() >= 30)) {
        expiry = getLastWednesday(today.getFullYear(), today.getMonth() + 1);
    }
    
    return expiry;
};

const formatFyersDate = (date) => {
    // Monthly Format: YYMMM (e.g., 25DEC)
    const year = date.getFullYear().toString().slice(-2);
    const monthNames = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    const monthStr = monthNames[date.getMonth()];
    
    return `${year}${monthStr}`;
};

const getOptionSymbols = (underlying, ltp, count = 10, step = 100) => {
    const atm = Math.round(ltp / step) * step;
    const expiryDate = getNextExpiry();
    const dateStr = formatFyersDate(expiryDate); // e.g., 25DEC
    
    const symbols = [];
    for (let i = -count; i <= count; i++) {
        const strike = atm + (i * step);
        // Symbol: NSE:BANKNIFTY25DEC46000CE
        symbols.push(`NSE:${underlying}${dateStr}${strike}CE`);
        symbols.push(`NSE:${underlying}${dateStr}${strike}PE`);
    }
    
    return symbols;
};

module.exports = { getNextExpiry, getOptionSymbols };
