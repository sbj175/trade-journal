// Trade Journal API Module
export class APIClient {
    constructor() {
        this.baseURL = '';
        this.defaultHeaders = {
            'Content-Type': 'application/json'
        };
    }
    
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            headers: { ...this.defaultHeaders, ...options.headers },
            ...options
        };
        
        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            }
            
            return await response.text();
        } catch (error) {
            console.error(`API request failed for ${endpoint}:`, error);
            throw error;
        }
    }
    
    // Account methods
    async getAccounts() {
        return this.request('/api/accounts');
    }
    
    async getAccountBalances() {
        return this.request('/api/account-balances');
    }
    
    // Dashboard methods
    async getDashboard(accountNumber = '') {
        const params = accountNumber ? `?account=${encodeURIComponent(accountNumber)}` : '';
        return this.request(`/api/dashboard${params}`);
    }
    
    // Order/Chain methods
    async getOrderChains(accountNumber = '') {
        const params = accountNumber ? `?account=${encodeURIComponent(accountNumber)}` : '';
        return this.request(`/api/chains${params}`);
    }
    
    async getAvailableUnderlyings(accountNumber = '') {
        const params = accountNumber ? `?account=${encodeURIComponent(accountNumber)}` : '';
        return this.request(`/api/available-underlyings${params}`);
    }
    
    // Position methods
    async getPositions(accountNumber = '') {
        const params = accountNumber ? `?account=${encodeURIComponent(accountNumber)}` : '';
        return this.request(`/api/positions${params}`);
    }
    
    // Sync methods
    async syncTrades() {
        return this.request('/api/sync', { method: 'POST' });
    }
    
    async syncPositions() {
        return this.request('/api/sync', { method: 'POST' });
    }
    
    async reprocessChains() {
        return this.request('/api/reprocess-chains', { method: 'POST' });
    }
    
    async initialSync() {
        return this.request('/api/sync/initial', { method: 'POST' });
    }
    
    // Trade edit methods
    async updateTrade(tradeId, data) {
        return this.request(`/api/trades/${tradeId}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    async updateOrder(orderId, data) {
        return this.request(`/api/orders/${orderId}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    // Quote methods
    async getQuote(symbol) {
        return this.request(`/api/quote/${encodeURIComponent(symbol)}`);
    }
    
    async getMultipleQuotes(symbols) {
        const symbolParams = symbols.map(s => `symbols=${encodeURIComponent(s)}`).join('&');
        return this.request(`/api/quotes?${symbolParams}`);
    }
    
    // Strategy config methods
    async getStrategies() {
        return this.request('/api/strategies');
    }
    
    async updateStrategy(strategyId, data) {
        return this.request(`/api/strategies/${strategyId}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    async createStrategy(data) {
        return this.request('/api/strategies', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    async deleteStrategy(strategyId) {
        return this.request(`/api/strategies/${strategyId}`, {
            method: 'DELETE'
        });
    }
}

// Create singleton instance
export const apiClient = new APIClient();