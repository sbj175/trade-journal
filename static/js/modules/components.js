// Trade Journal Alpine.js Components Module
import { stateManager } from './state.js';
import { apiClient } from './api.js';
import { formatCurrency, formatPercentage, formatDate, sortData, filterData, debounce } from './utils.js';

// Base component for order chains page
export function tradeJournalComponent() {
    return {
        // Initialize with state manager
        ...stateManager.getState(),
        
        // Computed properties
        get filteredChains() {
            const chains = stateManager.getState('chains') || [];
            const filters = stateManager.getState('filters');
            const sort = stateManager.getState('sort');
            
            let filtered = filterData(chains, filters);
            return sortData(filtered, sort.column, sort.direction);
        },
        
        get selectedAccountName() {
            const accounts = stateManager.getState('accounts');
            const selectedAccount = stateManager.getState('selectedAccount');
            const account = accounts.find(a => a.account_number === selectedAccount);
            return account ? account.account_name : 'All Accounts';
        },
        
        // Event handlers
        async init() {
            console.log('Initializing Trade Journal...');
            
            // Subscribe to state changes
            this.subscribeToStateChanges();
            
            // Load initial data
            await this.loadAccounts();
            await this.restoreAccountFromURL();
            await this.loadDashboard();
            await this.loadAvailableUnderlyings();
            await this.loadChains();
            
            console.log('Trade Journal initialized');
        },
        
        subscribeToStateChanges() {
            // Subscribe to various state changes to update UI
            stateManager.subscribe('selectedAccount', (account) => {
                this.selectedAccount = account;
                this.loadDashboard();
                this.loadChains();
            });
            
            stateManager.subscribe('chains', (chains) => {
                this.chains = chains;
            });
            
            stateManager.subscribe('loading', (loading) => {
                this.loading = loading;
            });
            
            stateManager.subscribe('syncing', (syncing) => {
                this.syncing = syncing;
            });
            
            stateManager.subscribe('filters.*', () => {
                // Filters changed, refresh computed filteredChains
                this.$nextTick(() => this.$refs.chainsContainer?.dispatchEvent(new Event('refresh')));
            });
        },
        
        async restoreAccountFromURL() {
            const urlParams = new URLSearchParams(window.location.search);
            const accountParam = urlParams.get('account');
            const underlyingParam = urlParams.get('underlying');
            
            if (accountParam) {
                const accounts = stateManager.getState('accounts');
                const accountExists = accounts.some(a => a.account_number === accountParam);
                if (accountExists) {
                    stateManager.setSelectedAccount(accountParam);
                }
            }
            
            if (underlyingParam) {
                const filters = stateManager.getState('filters');
                stateManager.updateFilters({ ...filters, underlying: underlyingParam });
            }
        },
        
        // API calls
        async loadAccounts() {
            try {
                const accounts = await apiClient.getAccounts();
                stateManager.setAccounts(accounts);
                this.accounts = accounts;
                
                // Set default account if none selected
                if (!stateManager.getSelectedAccount() && accounts.length > 0) {
                    stateManager.setSelectedAccount(accounts[0].account_number);
                }
            } catch (error) {
                console.error('Failed to load accounts:', error);
                this.showErrorMessage('Failed to load accounts');
            }
        },
        
        async loadDashboard() {
            try {
                stateManager.setLoading(true);
                const selectedAccount = stateManager.getSelectedAccount();
                const dashboard = await apiClient.getDashboard(selectedAccount);
                stateManager.setDashboard(dashboard);
                this.dashboard = dashboard;
            } catch (error) {
                console.error('Failed to load dashboard:', error);
                this.showErrorMessage('Failed to load dashboard data');
            } finally {
                stateManager.setLoading(false);
            }
        },
        
        async loadAvailableUnderlyings() {
            try {
                const selectedAccount = stateManager.getSelectedAccount();
                const underlyings = await apiClient.getAvailableUnderlyings(selectedAccount);
                stateManager.setState('availableUnderlyings', underlyings);
                this.availableUnderlyings = underlyings;
            } catch (error) {
                console.error('Failed to load underlyings:', error);
            }
        },
        
        async loadChains() {
            try {
                stateManager.setState('chainsLoading', true);
                this.chainsLoading = true;
                
                const selectedAccount = stateManager.getSelectedAccount();
                const chains = await apiClient.getOrderChains(selectedAccount);
                stateManager.setChains(chains);
                this.chains = chains;
            } catch (error) {
                console.error('Failed to load chains:', error);
                this.showErrorMessage('Failed to load order chains');
            } finally {
                stateManager.setState('chainsLoading', false);
                this.chainsLoading = false;
            }
        },
        
        // Sync operations
        async syncTrades() {
            try {
                stateManager.setSyncing(true);
                this.syncing = true;
                
                const result = await apiClient.syncTrades();
                console.log('Sync result:', result);
                
                // Reload data after sync
                await this.loadDashboard();
                await this.loadChains();
                await this.loadAvailableUnderlyings();
                
                stateManager.setState('lastSyncTimestamp', new Date().toLocaleString());
                this.lastSyncTimestamp = stateManager.getState('lastSyncTimestamp');
                
                this.showSuccessMessage(`Synced ${result.transactions_processed || 0} transactions`);
            } catch (error) {
                console.error('Sync failed:', error);
                this.showErrorMessage('Sync failed. Please try again.');
            } finally {
                stateManager.setSyncing(false);
                this.syncing = false;
            }
        },
        
        async initialSync() {
            try {
                stateManager.setState('initialSyncing', true);
                this.initialSyncing = true;
                
                const result = await apiClient.initialSync();
                console.log('Initial sync result:', result);
                
                // Reload data after sync
                await this.loadDashboard();
                await this.loadChains();
                await this.loadAvailableUnderlyings();
                
                this.showSuccessMessage('Initial sync completed');
            } catch (error) {
                console.error('Initial sync failed:', error);
                this.showErrorMessage('Initial sync failed. Please try again.');
            } finally {
                stateManager.setState('initialSyncing', false);
                this.initialSyncing = false;
            }
        },
        
        async reprocessChains() {
            try {
                stateManager.setState('reprocessing', true);
                this.reprocessing = true;
                
                const result = await apiClient.reprocessChains();
                console.log('Reprocess result:', result);
                
                // Reload chains after reprocessing
                await this.loadChains();
                
                this.showSuccessMessage('Chains reprocessed successfully');
            } catch (error) {
                console.error('Reprocess failed:', error);
                this.showErrorMessage('Reprocess failed. Please try again.');
            } finally {
                stateManager.setState('reprocessing', false);
                this.reprocessing = false;
            }
        },
        
        // Account selection
        selectAccount(accountNumber) {
            stateManager.setSelectedAccount(accountNumber);
        },
        
        // Filter methods
        updateFilter(filterName, value) {
            const filters = stateManager.getState('filters');
            stateManager.updateFilters({ ...filters, [filterName]: value });
        },
        
        clearFilters() {
            stateManager.updateFilters({
                searchTerm: '',
                status: '',
                strategy: '',
                underlying: '',
                showOpen: true,
                showClosed: true
            });
        },
        
        // Sorting
        sortBy(column) {
            const currentSort = stateManager.getState('sort');
            const direction = currentSort.column === column && currentSort.direction === 'asc' ? 'desc' : 'asc';
            stateManager.updateSort(column, direction);
        },
        
        // Utility methods
        formatCurrency,
        formatPercentage,
        formatDate,
        
        // UI feedback
        showSuccessMessage(message) {
            // Implementation depends on your notification system
            console.log('Success:', message);
        },
        
        showErrorMessage(message) {
            // Implementation depends on your notification system
            console.error('Error:', message);
        },
        
        // Debounced search
        debouncedSearch: debounce(function(searchTerm) {
            this.updateFilter('searchTerm', searchTerm);
        }, 300)
    };
}

// Base component for positions page
export function positionsComponent() {
    return {
        // Data
        allPositions: [],
        filteredPositions: [],
        accounts: [],
        accountBalances: {},
        underlyings: [],
        underlyingQuotes: {},
        positionComments: {},
        
        // WebSocket for live quotes
        ws: null,
        wsReconnectTimer: null,
        wsReconnectDelay: 5000,
        
        // Filters
        selectedAccount: '',
        selectedInstrumentType: '',
        selectedUnderlying: '',
        
        // State
        isLoading: false,
        error: null,
        liveQuotesActive: false,
        lastQuoteUpdate: null,
        lastSyncTimestamp: '',
        cacheInfo: null,
        
        // Computed properties
        get totalUnrealizedPnL() {
            return this.filteredPositions.reduce((sum, pos) => sum + this.getLiveUnrealizedPnL(pos), 0);
        },
        
        get currentAccountBalance() {
            if (!this.selectedAccount || this.selectedAccount === '') {
                const values = Object.values(this.accountBalances);
                if (values.length === 0) return null;
                
                return values.reduce((acc, balance) => ({
                    cash_balance: (acc.cash_balance || 0) + (balance.cash_balance || 0),
                    derivative_buying_power: (acc.derivative_buying_power || 0) + (balance.derivative_buying_power || 0),
                    net_liquidating_value: (acc.net_liquidating_value || 0) + (balance.net_liquidating_value || 0)
                }), { cash_balance: 0, derivative_buying_power: 0, net_liquidating_value: 0 });
            }
            return this.accountBalances[this.selectedAccount] || null;
        },
        
        get groupedPositions() {
            if (this.isLoading || !this.allPositions || this.allPositions.length === 0) {
                return [];
            }
            
            const groups = new Map();
            this.filteredPositions.forEach(position => {
                const underlying = this.getUnderlyingSymbol(position);
                if (!underlying || underlying === 'Unknown') return;
                
                if (!groups.has(underlying)) {
                    groups.set(underlying, []);
                }
                groups.get(underlying).push(position);
            });
            
            const sortedGroups = Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
            
            sortedGroups.forEach(([underlying, positions]) => {
                positions.sort((a, b) => {
                    if (a.instrument_type === 'EQUITY' && b.instrument_type !== 'EQUITY') return -1;
                    if (a.instrument_type !== 'EQUITY' && b.instrument_type === 'EQUITY') return 1;
                    
                    if (a.instrument_type !== 'EQUITY' && b.instrument_type !== 'EQUITY') {
                        if (a.expires_at && b.expires_at && a.expires_at !== b.expires_at) {
                            return new Date(a.expires_at) - new Date(b.expires_at);
                        }
                        
                        const strikeA = this.getNumericStrikePrice(a);
                        const strikeB = this.getNumericStrikePrice(b);
                        if (strikeA !== strikeB) return strikeA - strikeB;
                        
                        if (a.option_type && b.option_type && a.option_type !== b.option_type) {
                            return a.option_type === 'CALL' ? -1 : 1;
                        }
                    }
                    
                    return 0;
                });
            });
            
            return sortedGroups;
        },
        
        // Initialize
        async init() {
            console.log('Initializing Positions page...');
            this.loadPersistedFilters();
            this.loadComments();
            await this.fetchAccounts();
            await this.fetchPositions();
            await this.initializeWebSocket();
            console.log('Positions page initialized');
        },
        
        // Persistence
        loadPersistedFilters() {
            try {
                const saved = localStorage.getItem('positionsFilters');
                if (saved) {
                    const filters = JSON.parse(saved);
                    this.selectedAccount = filters.selectedAccount || '';
                    this.selectedInstrumentType = filters.selectedInstrumentType || '';
                    this.selectedUnderlying = filters.selectedUnderlying || '';
                }
            } catch (error) {
                console.warn('Failed to load persisted filters:', error);
            }
        },
        
        saveFilters() {
            try {
                const filters = {
                    selectedAccount: this.selectedAccount,
                    selectedInstrumentType: this.selectedInstrumentType,
                    selectedUnderlying: this.selectedUnderlying
                };
                localStorage.setItem('positionsFilters', JSON.stringify(filters));
            } catch (error) {
                console.warn('Failed to save filters:', error);
            }
        },
        
        // Data loading
        async fetchAccounts() {
            try {
                this.accounts = await apiClient.getAccounts();
            } catch (error) {
                console.error('Failed to fetch accounts:', error);
                this.error = 'Failed to load accounts';
            }
        },
        
        async fetchPositions(includeSync = false) {
            this.isLoading = true;
            this.error = null;
            
            try {
                if (includeSync) {
                    // Sync is a separate operation - use the main sync endpoint
                    await apiClient.syncTrades();
                }
                
                const selectedAccount = this.selectedAccount || '';
                const response = await apiClient.getPositions(selectedAccount);
                
                // Flatten positions from all accounts if response is grouped by account
                if (typeof response === 'object' && !Array.isArray(response)) {
                    this.allPositions = [];
                    Object.values(response).forEach(accountPositions => {
                        if (Array.isArray(accountPositions)) {
                            this.allPositions.push(...accountPositions);
                        }
                    });
                } else {
                    this.allPositions = Array.isArray(response) ? response : [];
                }
                
                this.cacheInfo = null; // No cache info in this response format
                this.lastSyncTimestamp = new Date().toLocaleString();
                
                await this.loadAccountBalances();
                this.applyFilters();
                this.requestLiveQuotes();
                
            } catch (error) {
                console.error('Failed to fetch positions:', error);
                this.error = 'Failed to load positions';
            } finally {
                this.isLoading = false;
            }
        },
        
        async loadAccountBalances() {
            try {
                const response = await apiClient.getAccountBalances();
                
                // Handle both direct array and nested response formats
                const balances = response.balances || response;
                
                // Convert array to object keyed by account_number
                this.accountBalances = {};
                if (Array.isArray(balances)) {
                    balances.forEach(balance => {
                        this.accountBalances[balance.account_number] = balance;
                    });
                }
            } catch (error) {
                console.error('Failed to load account balances:', error);
            }
        },
        
        // Filtering
        applyFilters() {
            this.filteredPositions = this.allPositions.filter(position => {
                if (this.selectedAccount && position.account_number !== this.selectedAccount) {
                    return false;
                }
                if (this.selectedInstrumentType && position.instrument_type !== this.selectedInstrumentType) {
                    return false;
                }
                if (this.selectedUnderlying) {
                    const underlying = this.getUnderlyingSymbol(position);
                    if (underlying !== this.selectedUnderlying) {
                        return false;
                    }
                }
                return true;
            });
            
            this.saveFilters();
        },
        
        filterByAccount(accountNumber) {
            this.selectedAccount = accountNumber;
            this.applyFilters();
        },
        
        filterByInstrumentType(type) {
            this.selectedInstrumentType = type;
            this.applyFilters();
        },
        
        filterByUnderlying(underlying) {
            this.selectedUnderlying = underlying;
            this.applyFilters();
        },
        
        clearFilters() {
            this.selectedAccount = '';
            this.selectedInstrumentType = '';
            this.selectedUnderlying = '';
            this.applyFilters();
        },
        
        // WebSocket for live quotes
        initializeWebSocket() {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.close();
            }
            
            try {
                const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${location.host}/ws/quotes`;
                
                this.ws = new WebSocket(wsUrl);
                
                this.ws.onopen = () => {
                    console.log('WebSocket connected for live quotes');
                    this.liveQuotesActive = true;
                    if (this.wsReconnectTimer) {
                        clearTimeout(this.wsReconnectTimer);
                        this.wsReconnectTimer = null;
                    }
                    this.requestLiveQuotes();
                };
                
                this.ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.symbol && typeof data.price === 'number') {
                            this.underlyingQuotes[data.symbol] = data;
                            this.lastQuoteUpdate = new Date().toLocaleTimeString();
                        }
                    } catch (error) {
                        console.error('Failed to parse quote message:', error);
                    }
                };
                
                this.ws.onclose = () => {
                    console.log('WebSocket connection closed');
                    this.liveQuotesActive = false;
                    this.scheduleReconnect();
                };
                
                this.ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    this.liveQuotesActive = false;
                };
                
            } catch (error) {
                console.error('Failed to initialize WebSocket:', error);
            }
        },
        
        scheduleReconnect() {
            if (this.wsReconnectTimer) {
                clearTimeout(this.wsReconnectTimer);
            }
            
            this.wsReconnectTimer = setTimeout(() => {
                console.log('Attempting to reconnect WebSocket...');
                this.initializeWebSocket();
            }, this.wsReconnectDelay);
        },
        
        requestLiveQuotes() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            
            const underlyings = [...new Set(this.filteredPositions.map(p => this.getUnderlyingSymbol(p)).filter(s => s && s !== 'Unknown'))];
            
            if (underlyings.length > 0) {
                const message = JSON.stringify({
                    action: 'subscribe',
                    symbols: underlyings
                });
                this.ws.send(message);
            }
        },
        
        // Utility methods
        getNumericStrikePrice(position) {
            if (!position.strike_price) return 0;
            const strike = parseFloat(position.strike_price);
            return isNaN(strike) ? 0 : strike;
        },
        
        getLiveUnrealizedPnL(position) {
            const underlying = this.getUnderlyingSymbol(position);
            const quote = this.underlyingQuotes[underlying];
            
            if (!quote || typeof quote.price !== 'number') {
                return position.unrealized_pnl || 0;
            }
            
            // Calculate based on current market price
            const currentPrice = quote.price;
            const quantity = position.quantity || 0;
            
            if (position.instrument_type === 'EQUITY') {
                const averagePrice = position.average_price || 0;
                return quantity * (currentPrice - averagePrice);
            }
            
            // For options, we'd need more complex calculations
            return position.unrealized_pnl || 0;
        },
        
        formatCurrency,
        formatPercentage,
        formatDate,
        
        // Additional utility methods for positions
        formatNumber(value, decimals = 0) {
            if (value === null || value === undefined || isNaN(value)) return '0';
            return new Intl.NumberFormat('en-US', {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            }).format(value);
        },
        
        
        getEfficiencyRatio(positions) {
            // Calculate efficiency ratio for multi-leg strategies
            if (!positions || positions.length <= 1) return null;
            
            // Check if this is a defined-risk strategy (not straddle/strangle)
            const strategies = positions.map(p => p.strategy).filter(Boolean);
            const strategy = strategies[0];
            if (!strategy || strategy.toLowerCase().includes('straddle') || strategy.toLowerCase().includes('strangle')) {
                return null;
            }
            
            // Calculate profit captured % and time elapsed %
            let totalPnL = 0;
            let totalMaxProfit = 0;
            let minOpenedAt = null;
            let maxExpiresAt = null;
            
            positions.forEach(position => {
                totalPnL += position.realized_pnl || 0;
                totalPnL += position.unrealized_pnl || 0;
                
                // Estimate max profit for spreads
                if (position.instrument_type !== 'EQUITY') {
                    const strike = parseFloat(position.strike_price) || 0;
                    const quantity = Math.abs(position.quantity) || 0;
                    totalMaxProfit += quantity * 100; // Rough estimate
                }
                
                if (position.opened_at) {
                    const openedAt = new Date(position.opened_at);
                    if (!minOpenedAt || openedAt < minOpenedAt) {
                        minOpenedAt = openedAt;
                    }
                }
                
                if (position.expires_at) {
                    const expiresAt = new Date(position.expires_at);
                    if (!maxExpiresAt || expiresAt > maxExpiresAt) {
                        maxExpiresAt = expiresAt;
                    }
                }
            });
            
            if (!minOpenedAt || !maxExpiresAt || totalMaxProfit <= 0) return null;
            
            const profitCapturedPct = (totalPnL / totalMaxProfit) * 100;
            
            const now = new Date();
            const totalTime = maxExpiresAt.getTime() - minOpenedAt.getTime();
            const elapsedTime = now.getTime() - minOpenedAt.getTime();
            const timeElapsedPct = (elapsedTime / totalTime) * 100;
            
            if (timeElapsedPct <= 0) return null;
            
            const efficiency = profitCapturedPct / timeElapsedPct;
            return efficiency > 0 ? efficiency : null;
        },
        
        getDisplayQuantity(position) {
            if (!position) return 0;
            const action = (position.closing_action || position.opening_action || '').toUpperCase();
            const isSellAction = action.includes('SELL') || action.includes('STC') || action.includes('STO');
            return isSellAction ? -Math.abs(position.quantity) : Math.abs(position.quantity);
        },
        
        getStrategyDisplayName(strategy) {
            if (!strategy) return 'Unknown';
            return strategy.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
        
        getUnderlyingSymbol(position) {
            // Extract underlying symbol from position
            if (position.underlying) {
                return position.underlying;
            }
            
            if (position.symbol) {
                if (position.instrument_type === 'EQUITY') {
                    return position.symbol;
                } else {
                    // For options, extract underlying from symbols like "CRDO 250919C00100000" -> "CRDO"
                    return position.symbol.split(' ')[0] || position.symbol.split('_')[0];
                }
            }
            
            return 'Unknown';
        },
        
        // Comment management
        getCommentKey(underlying, account) {
            return `${underlying}_${account || 'default'}`;
        },
        
        getComment(underlying, account) {
            const key = this.getCommentKey(underlying, account);
            return this.positionComments[key] || '';
        },
        
        saveComment(underlying, account, comment) {
            const key = this.getCommentKey(underlying, account);
            this.positionComments[key] = comment;
            
            // Persist to localStorage
            try {
                localStorage.setItem('positionComments', JSON.stringify(this.positionComments));
            } catch (error) {
                console.warn('Failed to save comments to localStorage:', error);
            }
        },
        
        loadComments() {
            try {
                const saved = localStorage.getItem('positionComments');
                if (saved) {
                    this.positionComments = JSON.parse(saved);
                }
            } catch (error) {
                console.warn('Failed to load comments from localStorage:', error);
                this.positionComments = {};
            }
        },
        
        // Position calculation functions
        getGroupCostBasis(positions) {
            return positions.reduce((sum, pos) => sum + this.getCostBasisDisplay(pos), 0);
        },
        
        getGroupNetLiq(positions) {
            return positions.reduce((sum, pos) => sum + this.getNetLiq(pos), 0);
        },
        
        getGroupPnL(positions) {
            return positions.reduce((sum, pos) => sum + this.getLiveUnrealizedPnL(pos), 0);
        },
        
        getCostBasisDisplay(position) {
            const costBasis = position.cost_basis || 0;
            const quantity = this.getSignedQuantity(position);
            
            if (quantity < 0) {
                // Short position: show negative cost basis
                return -Math.abs(costBasis);
            }
            return costBasis;
        },
        
        getNetLiq(position) {
            // For option positions, use live quote data if available
            if (position.instrument_type && position.instrument_type.includes('OPTION')) {
                const quote = this.underlyingQuotes[position.symbol];
                if (quote && quote.mark) {
                    // Calculate live NetLiq: quantity * mark_price * 100 (for options)
                    const quantity = this.getSignedQuantity(position);
                    return quantity * quote.mark * 100;
                }
            }
            
            // For equity or when no live data available, use market_value
            return position.market_value || 0;
        },
        
        getSignedQuantity(position) {
            if (!position) return 0;
            
            const quantity = Math.abs(position.quantity || 0);
            const action = (position.closing_action || position.opening_action || '').toLowerCase();
            
            // Determine if this is a short position
            const isShort = action.includes('sell') || action.includes('sto') || action.includes('stc');
            
            return isShort ? -quantity : quantity;
        },
        
        getUnderlyingQuote(underlying) {
            const quote = this.underlyingQuotes[underlying];
            
            if (!quote) {
                return null;
            }
            
            return {
                price: quote.price || quote.last || 0,
                change: quote.change || 0,
                changePercent: quote.changePercent || ((quote.price - quote.previousClose) / quote.previousClose * 100) || 0,
                mark: quote.mark || quote.price || quote.last || 0
            };
        },
        
        getUnderlyingIV(underlying) {
            const quote = this.underlyingQuotes[underlying];
            
            if (!quote || !quote.impliedVolatility) {
                return null;
            }
            
            return (quote.impliedVolatility * 100).toFixed(0) + '%';
        },
        
        getMinDTE(positions) {
            // Get the minimum DTE from all option positions in the group
            const optionPositions = positions.filter(p => p.instrument_type && p.instrument_type.includes('OPTION'));
            
            if (optionPositions.length === 0) return null;
            
            const dtes = optionPositions.map(p => this.getDTE(p)).filter(dte => dte !== null);
            
            return dtes.length > 0 ? Math.min(...dtes) : null;
        },
        
        shouldShowEfficiencyRatio(positions) {
            // Show efficiency ratio for multi-leg strategies only
            if (!positions || positions.length <= 1) return false;
            
            // Check if this is a defined-risk strategy (not straddle/strangle)
            const strategies = positions.map(p => p.strategy).filter(Boolean);
            const strategy = strategies[0] || '';
            
            return !strategy.toLowerCase().includes('straddle') && !strategy.toLowerCase().includes('strangle');
        },
        
        getGroupEfficiencyRatio(positions) {
            if (!this.shouldShowEfficiencyRatio(positions)) {
                return '—';
            }
            
            const efficiency = this.getEfficiencyRatio(positions);
            return efficiency !== null && efficiency > 0 ? efficiency.toFixed(1) : '—';
        },
        
        getEfficiencyRatioColor(ratio) {
            if (ratio === '—' || ratio === null) return 'text-slate-400';
            
            const numRatio = parseFloat(ratio);
            if (numRatio >= 2.0) return 'text-green-400';
            if (numRatio >= 1.0) return 'text-blue-400';
            if (numRatio >= 0.5) return 'text-yellow-400';
            return 'text-red-400';
        },
        
        getEfficiencyTooltip(positions) {
            if (!this.shouldShowEfficiencyRatio(positions)) return '';
            
            const currentPnL = this.getGroupPnL(positions);
            const costBasis = Math.abs(this.getGroupCostBasis(positions));
            const profitCapturedPercent = costBasis > 0 ? (currentPnL / costBasis) * 100 : 0;
            
            const minDTE = this.getMinDTE(positions);
            const daysOpen = minDTE !== null ? Math.max(1, 45 - minDTE) : 1; // Rough estimate
            
            return `${profitCapturedPercent.toFixed(0)}% profit captured in ${daysOpen} days`;
        },
        
        // Individual position functions
        getStrategyLabel(positions) {
            if (!positions || positions.length === 0) return '';
            
            // Get strategy from first position
            const strategy = positions[0].strategy || 'Unknown';
            return this.getStrategyDisplayName(strategy);
        },
        
        getOptionType(position) {
            if (!position || position.instrument_type === 'EQUITY') {
                return 'Stock';
            }
            
            return position.option_type === 'CALL' ? 'Call' : position.option_type === 'PUT' ? 'Put' : 'Option';
        },
        
        getExpirationDate(position) {
            if (!position.expires_at) return '';
            
            try {
                const date = new Date(position.expires_at);
                return date.toLocaleDateString('en-US', { 
                    month: 'short', 
                    day: 'numeric', 
                    year: '2-digit' 
                });
            } catch (error) {
                return position.expires_at;
            }
        },
        
        getStrikePrice(position) {
            if (!position.strike_price) return '';
            
            const strike = parseFloat(position.strike_price);
            return isNaN(strike) ? '' : strike.toFixed(2);
        },
        
        getDTE(position) {
            if (!position || !position.expires_at) return null;
            
            try {
                const expDate = new Date(position.expires_at);
                const now = new Date();
                const diffTime = expDate.getTime() - now.getTime();
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
                return Math.max(0, diffDays);
            } catch (error) {
                return null;
            }
        }
    };
}