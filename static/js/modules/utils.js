// Trade Journal Utility Functions Module

// Formatting utilities
export const formatCurrency = (value, options = {}) => {
    const {
        currency = 'USD',
        minimumFractionDigits = 2,
        maximumFractionDigits = 2,
        showSign = false
    } = options;
    
    if (value === null || value === undefined || isNaN(value)) {
        return '$0.00';
    }
    
    const formatter = new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency,
        minimumFractionDigits,
        maximumFractionDigits
    });
    
    const formatted = formatter.format(Math.abs(value));
    
    if (showSign && value !== 0) {
        return value > 0 ? `+${formatted}` : `-${formatted}`;
    }
    
    return value < 0 ? `-${formatted}` : formatted;
};

export const formatPercentage = (value, options = {}) => {
    const {
        minimumFractionDigits = 1,
        maximumFractionDigits = 1,
        showSign = false
    } = options;
    
    if (value === null || value === undefined || isNaN(value)) {
        return '0.0%';
    }
    
    const formatter = new Intl.NumberFormat('en-US', {
        style: 'percent',
        minimumFractionDigits,
        maximumFractionDigits
    });
    
    const formatted = formatter.format(Math.abs(value / 100));
    
    if (showSign && value !== 0) {
        return value > 0 ? `+${formatted}` : `-${formatted}`;
    }
    
    return value < 0 ? `-${formatted}` : formatted;
};

export const formatNumber = (value, options = {}) => {
    const {
        minimumFractionDigits = 0,
        maximumFractionDigits = 2,
        showSign = false
    } = options;
    
    if (value === null || value === undefined || isNaN(value)) {
        return '0';
    }
    
    const formatter = new Intl.NumberFormat('en-US', {
        minimumFractionDigits,
        maximumFractionDigits
    });
    
    const formatted = formatter.format(Math.abs(value));
    
    if (showSign && value !== 0) {
        return value > 0 ? `+${formatted}` : `-${formatted}`;
    }
    
    return value < 0 ? `-${formatted}` : formatted;
};

// Date utilities
export const formatDate = (dateStr, options = {}) => {
    const {
        includeTime = false,
        timeZone = 'America/New_York'
    } = options;
    
    if (!dateStr) return '';
    
    try {
        const date = new Date(dateStr);
        
        if (includeTime) {
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                timeZone
            });
        }
        
        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            timeZone
        });
    } catch (error) {
        console.warn('Failed to format date:', dateStr, error);
        return dateStr;
    }
};

export const formatTime = (dateStr, options = {}) => {
    const { timeZone = 'America/New_York' } = options;
    
    if (!dateStr) return '';
    
    try {
        const date = new Date(dateStr);
        return date.toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            timeZone
        });
    } catch (error) {
        console.warn('Failed to format time:', dateStr, error);
        return dateStr;
    }
};

export const calculateDaysToExpiration = (expirationDate) => {
    if (!expirationDate) return null;
    
    try {
        const expDate = new Date(expirationDate);
        const now = new Date();
        const diffTime = expDate.getTime() - now.getTime();
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        return Math.max(0, diffDays);
    } catch (error) {
        console.warn('Failed to calculate DTE:', expirationDate, error);
        return null;
    }
};

// Option utilities
export const parseOptionSymbol = (symbol) => {
    if (!symbol) return null;
    
    // Match pattern: UNDERLYING_MMDDYY_TYPE_STRIKE
    // Example: AAPL_012124_C_150 or AAPL_012124_P_145.5
    const optionPattern = /^([A-Z]+)_(\d{6})_([CP])_(\d+(?:\.\d+)?)$/;
    const match = symbol.match(optionPattern);
    
    if (!match) return null;
    
    const [, underlying, dateStr, type, strikeStr] = match;
    
    // Parse date (MMDDYY format)
    const month = dateStr.substring(0, 2);
    const day = dateStr.substring(2, 4);
    const year = '20' + dateStr.substring(4, 6);
    const expirationDate = `${year}-${month}-${day}`;
    
    return {
        underlying,
        expirationDate,
        optionType: type === 'C' ? 'CALL' : 'PUT',
        strike: parseFloat(strikeStr),
        symbol
    };
};

export const getDisplayQuantity = (position) => {
    if (!position) return 0;
    
    const action = (position.closing_action || position.opening_action || '').toUpperCase();
    const isSellAction = action.includes('SELL') || action.includes('STC') || action.includes('STO');
    
    return isSellAction ? -Math.abs(position.quantity) : Math.abs(position.quantity);
};

// Strategy utilities
export const getStrategyDisplayName = (strategy) => {
    if (!strategy) return 'Unknown';
    
    // Convert from database format to display format
    const strategyMap = {
        'iron_condor': 'Iron Condor',
        'iron_butterfly': 'Iron Butterfly',
        'call_spread': 'Call Spread',
        'put_spread': 'Put Spread',
        'covered_call': 'Covered Call',
        'cash_secured_put': 'Cash Secured Put',
        'long_call': 'Long Call',
        'long_put': 'Long Put',
        'short_call': 'Short Call',
        'short_put': 'Short Put',
        'straddle': 'Straddle',
        'strangle': 'Strangle',
        'butterfly': 'Butterfly',
        'condor': 'Condor'
    };
    
    return strategyMap[strategy] || strategy.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// Validation utilities
export const isValidSymbol = (symbol) => {
    if (!symbol || typeof symbol !== 'string') return false;
    return /^[A-Z]{1,5}$/.test(symbol.trim());
};

export const isValidOptionSymbol = (symbol) => {
    return parseOptionSymbol(symbol) !== null;
};

// Sorting utilities
export const sortData = (data, column, direction) => {
    if (!Array.isArray(data)) return data;
    
    return [...data].sort((a, b) => {
        let aVal = a[column];
        let bVal = b[column];
        
        // Handle nested properties
        if (column.includes('.')) {
            const keys = column.split('.');
            aVal = keys.reduce((obj, key) => obj?.[key], a);
            bVal = keys.reduce((obj, key) => obj?.[key], b);
        }
        
        // Handle null/undefined values
        if (aVal == null && bVal == null) return 0;
        if (aVal == null) return direction === 'asc' ? -1 : 1;
        if (bVal == null) return direction === 'asc' ? 1 : -1;
        
        // Handle different data types
        if (typeof aVal === 'number' && typeof bVal === 'number') {
            return direction === 'asc' ? aVal - bVal : bVal - aVal;
        }
        
        if (typeof aVal === 'string' && typeof bVal === 'string') {
            const comparison = aVal.localeCompare(bVal);
            return direction === 'asc' ? comparison : -comparison;
        }
        
        // Convert to strings for comparison
        const aStr = String(aVal).toLowerCase();
        const bStr = String(bVal).toLowerCase();
        const comparison = aStr.localeCompare(bStr);
        return direction === 'asc' ? comparison : -comparison;
    });
};

// Filter utilities
export const filterData = (data, filters) => {
    if (!Array.isArray(data)) return data;
    
    return data.filter(item => {
        // Search term filter
        if (filters.searchTerm) {
            const searchLower = filters.searchTerm.toLowerCase();
            const searchableFields = ['underlying', 'strategy', 'status'];
            const matches = searchableFields.some(field => {
                const value = item[field];
                return value && String(value).toLowerCase().includes(searchLower);
            });
            if (!matches) return false;
        }
        
        // Status filter
        if (filters.status && item.status !== filters.status) {
            return false;
        }
        
        // Strategy filter
        if (filters.strategy && item.strategy !== filters.strategy) {
            return false;
        }
        
        // Underlying filter
        if (filters.underlying && item.underlying !== filters.underlying) {
            return false;
        }
        
        // Show open/closed filters
        if (!filters.showOpen && item.status === 'OPEN') {
            return false;
        }
        
        if (!filters.showClosed && item.status === 'CLOSED') {
            return false;
        }
        
        return true;
    });
};

// WebSocket utilities
export const createWebSocketConnection = (endpoint, onMessage, onError, onClose) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${endpoint}`;
    
    const ws = new WebSocket(wsUrl);
    
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            onMessage(data);
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
            if (onError) onError(error);
        }
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        if (onError) onError(error);
    };
    
    ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);
        if (onClose) onClose(event);
    };
    
    return ws;
};

// Local storage utilities
export const getStoredComments = (key) => {
    try {
        const stored = localStorage.getItem(`comments_${key}`);
        return stored ? JSON.parse(stored) : {};
    } catch (error) {
        console.warn('Failed to load comments from localStorage:', error);
        return {};
    }
};

export const setStoredComments = (key, comments) => {
    try {
        localStorage.setItem(`comments_${key}`, JSON.stringify(comments));
    } catch (error) {
        console.warn('Failed to save comments to localStorage:', error);
    }
};

// Debounce utility
export const debounce = (func, delay) => {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(null, args), delay);
    };
};