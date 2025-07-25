// Trade Journal State Management Module
export class StateManager {
    constructor() {
        this.state = {
            // Account state
            accounts: [],
            selectedAccount: '',
            
            // Data state
            trades: [],
            chains: [],
            positions: [],
            availableUnderlyings: [],
            
            // Dashboard state
            dashboard: {
                summary: {
                    total_pnl: 0,
                    today_pnl: 0,
                    week_pnl: 0,
                    win_rate: 0,
                    open_trades: 0,
                    closed_trades: 0,
                    total_trades: 0
                },
                filteredSummary: {
                    total_pnl: 0,
                    realized_pnl: 0,
                    unrealized_pnl: 0,
                    win_rate: 0,
                    open_chains: 0,
                    closed_chains: 0,
                    total_chains: 0
                },
                strategy_breakdown: [],
                recent_trades: []
            },
            
            // UI state
            loading: false,
            syncing: false,
            lastSyncTimestamp: '',
            
            // Filter state
            filters: {
                searchTerm: '',
                status: '',
                strategy: '',
                underlying: '',
                showOpen: true,
                showClosed: true
            },
            
            // Sort state
            sort: {
                column: 'underlying',
                direction: 'asc'
            },
            
            // Modal state
            modals: {
                editModalOpen: false,
                editingTrade: null,
                tradeDetailsModalOpen: false,
                loadingTradeDetails: false,
                tradeDetails: null
            }
        };
        
        this.listeners = new Map();
        this.loadSavedState();
    }
    
    // State getters
    getState(path = null) {
        if (!path) return this.state;
        
        const keys = path.split('.');
        let value = this.state;
        for (const key of keys) {
            value = value?.[key];
        }
        return value;
    }
    
    // State setters
    setState(path, value, notify = true) {
        const keys = path.split('.');
        const lastKey = keys.pop();
        let target = this.state;
        
        for (const key of keys) {
            if (!(key in target)) target[key] = {};
            target = target[key];
        }
        
        const oldValue = target[lastKey];
        target[lastKey] = value;
        
        if (notify && oldValue !== value) {
            this.notifyListeners(path, value, oldValue);
        }
        
        // Save certain state changes to localStorage
        if (path === 'selectedAccount') {
            this.saveStateToStorage();
        }
    }
    
    // Batch state updates
    batchUpdate(updates, notify = true) {
        const changes = [];
        
        for (const [path, value] of Object.entries(updates)) {
            const oldValue = this.getState(path);
            this.setState(path, value, false);
            if (oldValue !== value) {
                changes.push({ path, value, oldValue });
            }
        }
        
        if (notify && changes.length > 0) {
            for (const change of changes) {
                this.notifyListeners(change.path, change.value, change.oldValue);
            }
        }
    }
    
    // Subscribe to state changes
    subscribe(path, callback) {
        if (!this.listeners.has(path)) {
            this.listeners.set(path, new Set());
        }
        this.listeners.get(path).add(callback);
        
        // Return unsubscribe function
        return () => {
            const pathListeners = this.listeners.get(path);
            if (pathListeners) {
                pathListeners.delete(callback);
                if (pathListeners.size === 0) {
                    this.listeners.delete(path);
                }
            }
        };
    }
    
    // Notify listeners of state changes
    notifyListeners(path, newValue, oldValue) {
        const pathListeners = this.listeners.get(path);
        if (pathListeners) {
            for (const callback of pathListeners) {
                try {
                    callback(newValue, oldValue, path);
                } catch (error) {
                    console.error('Error in state listener:', error);
                }
            }
        }
        
        // Also notify wildcard listeners (listening to parent paths)
        const pathParts = path.split('.');
        for (let i = pathParts.length - 1; i > 0; i--) {
            const parentPath = pathParts.slice(0, i).join('.');
            const parentListeners = this.listeners.get(parentPath + '.*');
            if (parentListeners) {
                for (const callback of parentListeners) {
                    try {
                        callback(newValue, oldValue, path);
                    } catch (error) {
                        console.error('Error in wildcard state listener:', error);
                    }
                }
            }
        }
    }
    
    // Persistence
    saveStateToStorage() {
        const persistedState = {
            selectedAccount: this.state.selectedAccount,
            filters: this.state.filters,
            sort: this.state.sort
        };
        
        try {
            localStorage.setItem('tradeJournalState', JSON.stringify(persistedState));
        } catch (error) {
            console.warn('Failed to save state to localStorage:', error);
        }
    }
    
    loadSavedState() {
        try {
            const saved = localStorage.getItem('tradeJournalState');
            if (saved) {
                const persistedState = JSON.parse(saved);
                
                // Restore saved state
                if (persistedState.selectedAccount) {
                    this.state.selectedAccount = persistedState.selectedAccount;
                }
                if (persistedState.filters) {
                    Object.assign(this.state.filters, persistedState.filters);
                }
                if (persistedState.sort) {
                    Object.assign(this.state.sort, persistedState.sort);
                }
            }
        } catch (error) {
            console.warn('Failed to load state from localStorage:', error);
        }
    }
    
    // Account helpers
    setSelectedAccount(accountNumber) {
        this.setState('selectedAccount', accountNumber);
    }
    
    getSelectedAccount() {
        return this.state.selectedAccount;
    }
    
    // Filter helpers
    updateFilters(filters) {
        const currentFilters = this.state.filters;
        const updatedFilters = { ...currentFilters, ...filters };
        this.setState('filters', updatedFilters);
    }
    
    // Sort helpers
    updateSort(column, direction) {
        this.setState('sort', { column, direction });
    }
    
    // UI state helpers
    setLoading(loading) {
        this.setState('loading', loading);
    }
    
    setSyncing(syncing) {
        this.setState('syncing', syncing);
    }
    
    // Data helpers
    setAccounts(accounts) {
        this.setState('accounts', accounts);
    }
    
    setChains(chains) {
        this.setState('chains', chains);
    }
    
    setPositions(positions) {
        this.setState('positions', positions);
    }
    
    setDashboard(dashboard) {
        this.setState('dashboard', dashboard);
    }
}

// Create singleton instance
export const stateManager = new StateManager();