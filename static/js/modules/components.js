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
                
                this.showSuccessMessage(`Synced ${result.saved_count} transactions`);
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
        // Initialize with state manager
        ...stateManager.getState(),
        
        // Positions-specific state
        positions: [],
        accountBalances: [],
        currentAccountBalance: null,
        quotes: {},
        websocket: null,
        comments: {},
        
        get currentAccountBalanceData() {
            const selectedAccount = stateManager.getSelectedAccount();
            return this.accountBalances.find(b => b.account_number === selectedAccount) || {};
        },
        
        // Initialize
        async init() {
            console.log('Initializing Positions page...');
            
            this.subscribeToStateChanges();
            await this.loadAccounts();
            await this.restoreAccountFromURL();
            await this.loadPositions();
            await this.loadAccountBalances();
            await this.initWebSocket();
            
            console.log('Positions page initialized');
        },
        
        subscribeToStateChanges() {
            stateManager.subscribe('selectedAccount', (account) => {
                this.selectedAccount = account;
                this.loadPositions();
                this.loadAccountBalances();
                this.updateCurrentAccountBalance();
            });
        },
        
        async restoreAccountFromURL() {
            const urlParams = new URLSearchParams(window.location.search);
            const accountParam = urlParams.get('account');
            
            if (accountParam) {
                const accounts = stateManager.getState('accounts');
                const accountExists = accounts.some(a => a.account_number === accountParam);
                if (accountExists) {
                    stateManager.setSelectedAccount(accountParam);
                }
            }
        },
        
        async loadAccounts() {
            try {
                const accounts = await apiClient.getAccounts();
                stateManager.setAccounts(accounts);
                this.accounts = accounts;
                
                if (!stateManager.getSelectedAccount() && accounts.length > 0) {
                    stateManager.setSelectedAccount(accounts[0].account_number);
                }
            } catch (error) {
                console.error('Failed to load accounts:', error);
            }
        },
        
        async loadPositions() {
            try {
                stateManager.setLoading(true);
                const selectedAccount = stateManager.getSelectedAccount();
                const positions = await apiClient.getPositions(selectedAccount);
                stateManager.setPositions(positions);
                this.positions = positions;
            } catch (error) {
                console.error('Failed to load positions:', error);
            } finally {
                stateManager.setLoading(false);
            }
        },
        
        async loadAccountBalances() {
            try {
                const balances = await apiClient.getAccountBalances();
                this.accountBalances = balances;
                this.updateCurrentAccountBalance();
            } catch (error) {
                console.error('Failed to load account balances:', error);
            }
        },
        
        updateCurrentAccountBalance() {
            const selectedAccount = stateManager.getSelectedAccount();
            this.currentAccountBalance = this.accountBalances.find(b => b.account_number === selectedAccount) || {};
        },
        
        async syncPositions() {
            try {
                stateManager.setSyncing(true);
                const result = await apiClient.syncPositions();
                console.log('Sync positions result:', result);
                
                await this.loadPositions();
                await this.loadAccountBalances();
                
                this.showSuccessMessage('Positions synced successfully');
            } catch (error) {
                console.error('Sync positions failed:', error);
                this.showErrorMessage('Failed to sync positions');
            } finally {
                stateManager.setSyncing(false);
            }
        },
        
        // WebSocket for live quotes
        async initWebSocket() {
            try {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${window.location.host}/ws/quotes`;
                
                this.websocket = new WebSocket(wsUrl);
                
                this.websocket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.symbol && data.price !== undefined) {
                            this.quotes[data.symbol] = data;
                        }
                    } catch (error) {
                        console.error('Failed to parse quote data:', error);
                    }
                };
                
                this.websocket.onclose = () => {
                    console.log('WebSocket connection closed');
                    // Attempt to reconnect after 5 seconds
                    setTimeout(() => this.initWebSocket(), 5000);
                };
                
                this.websocket.onerror = (error) => {
                    console.error('WebSocket error:', error);
                };
                
            } catch (error) {
                console.error('Failed to initialize WebSocket:', error);
            }
        },
        
        // Utility methods
        selectAccount(accountNumber) {
            stateManager.setSelectedAccount(accountNumber);
        },
        
        formatCurrency,
        formatPercentage,
        formatDate,
        
        showSuccessMessage(message) {
            console.log('Success:', message);
        },
        
        showErrorMessage(message) {
            console.error('Error:', message);
        }
    };
}