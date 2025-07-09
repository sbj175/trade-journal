// Trade Journal Alpine.js Application - Fixed Version
function tradeJournal() {
    return {
        // State
        trades: [],
        chains: [],
        accounts: [],
        selectedAccount: '',
        availableUnderlyings: [],
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
            strategy_breakdown: [],
            recent_trades: []
        },
        
        // UI State
        loading: false,
        chainsLoading: false,
        syncing: false,
        initialSyncing: false,
        reprocessing: false,
        lastSyncTimestamp: '',
        
        // Filters
        searchTerm: '',
        filterStatus: '',
        filterStrategy: '',
        filterUnderlying: '',
        showOpen: true,
        showClosed: true,
        filteredChains: [],
        
        // Sorting
        sortColumn: 'underlying',
        sortDirection: 'asc',
        
        // Modal state
        editModalOpen: false,
        editingTrade: null,
        
        
        // Trade details modal state (legacy)
        tradeDetailsModalOpen: false,
        loadingTradeDetails: false,
        tradeDetails: null,
        
        // Initialize
        async init() {
            console.log('Initializing Trade Journal...');
            
            // Get saved state before loading data
            const savedState = this.getSavedState();
            
            // Load accounts and set the saved one if it exists
            await this.loadAccounts();
            
            // Apply saved account after accounts are loaded
            if (savedState && savedState.selectedAccount) {
                const accountExists = this.accounts.some(a => a.account_number === savedState.selectedAccount);
                if (accountExists) {
                    this.selectedAccount = savedState.selectedAccount;
                    console.log('Restored account:', savedState.selectedAccount);
                } else {
                    console.log('Saved account not found:', savedState.selectedAccount);
                }
            }
            
            // Load dashboard with selected account
            await this.loadDashboard();
            
            // Load available underlyings
            await this.loadAvailableUnderlyings();
            
            // Check for URL parameters first (e.g., from positions page links)
            const urlParams = new URLSearchParams(window.location.search);
            const underlyingParam = urlParams.get('underlying');
            const accountParam = urlParams.get('account');
            
            // Apply URL parameter account filter if provided and account exists
            if (accountParam) {
                const accountExists = this.accounts.some(a => a.account_number === accountParam);
                if (accountExists) {
                    this.selectedAccount = accountParam;
                    console.log('Applied URL parameter account filter:', accountParam);
                    // Reload data with new account
                    await this.loadDashboard();
                    await this.loadAvailableUnderlyings();
                }
            }
            
            // Apply URL parameter underlying filter if provided (don't require it to be in available list yet)
            if (underlyingParam) {
                this.filterUnderlying = underlyingParam;
                console.log('Applied URL parameter underlying filter:', underlyingParam);
            }
            
            // Clear URL parameters after applying them
            if (underlyingParam || accountParam) {
                window.history.replaceState({}, document.title, window.location.pathname);
            }
            
            // Apply saved underlying if no URL parameter was provided
            if (!underlyingParam && savedState && savedState.filterUnderlying) {
                if (this.availableUnderlyings.includes(savedState.filterUnderlying)) {
                    this.filterUnderlying = savedState.filterUnderlying;
                    console.log('Restored underlying:', savedState.filterUnderlying);
                } else {
                    console.log('Saved underlying not found:', savedState.filterUnderlying);
                }
            }
            
            // Apply other saved filters
            if (savedState) {
                this.filterStrategy = savedState.filterStrategy || '';
                this.filterStatus = savedState.filterStatus || '';
                this.sortColumn = savedState.sortColumn || 'underlying';
                this.sortDirection = savedState.sortDirection || 'asc';
                this.showOpen = savedState.showOpen !== undefined ? savedState.showOpen : true;
                this.showClosed = savedState.showClosed !== undefined ? savedState.showClosed : true;
                console.log('Restored other filters:', {
                    strategy: this.filterStrategy,
                    status: this.filterStatus,
                    showOpen: this.showOpen,
                    showClosed: this.showClosed
                });
            }
            
            // Load trades and chains with restored filters
            await this.loadChains();
            
            // Load last sync timestamp
            await this.loadLastSyncTimestamp();
            
            // Double-check dropdowns after everything is loaded
            this.$nextTick(() => {
                this.verifyDropdownValues();
                
                // Log final state for debugging
                console.log('Final state after initialization:', {
                    selectedAccount: this.selectedAccount,
                    filterUnderlying: this.filterUnderlying,
                    availableUnderlyings: this.availableUnderlyings.length,
                    chainsLoaded: this.chains.length
                });
            });
        },
        
        // Load accounts
        async loadAccounts() {
            try {
                console.log('Loading accounts...');
                const response = await fetch('/api/accounts');
                const data = await response.json();
                this.accounts = data.accounts || [];
                
                // Sort accounts in desired order: Roth, Individual, Traditional
                this.accounts.sort((a, b) => {
                    const getAccountTypeOrder = (name) => {
                        const nameUpper = (name || '').toUpperCase();
                        if (nameUpper.includes('ROTH')) return 1;
                        if (nameUpper.includes('INDIVIDUAL')) return 2;
                        if (nameUpper.includes('TRADITIONAL')) return 3;
                        return 4; // Other account types go last
                    };
                    
                    const orderA = getAccountTypeOrder(a.account_name);
                    const orderB = getAccountTypeOrder(b.account_name);
                    
                    return orderA - orderB;
                });
                
                // Set default account (first one) only if no account is selected
                if (this.accounts.length > 0 && !this.selectedAccount) {
                    this.selectedAccount = this.accounts[0].account_number;
                }
                console.log(`Loaded ${this.accounts.length} accounts`);
            } catch (error) {
                console.error('Error loading accounts:', error);
            }
        },
        
        // Handle account change
        async onAccountChange() {
            console.log('Account changed to:', this.selectedAccount);
            
            // Reset underlying filter when account changes
            this.filterUnderlying = '';
            console.log('Reset underlying filter to All');
            
            this.saveState(); // Save state after resetting underlying
            
            await this.loadDashboard();
            await this.loadAvailableUnderlyings();
            await this.loadChains();
        },
        
        // Format number with commas
        formatNumber(num) {
            if (num === null || num === undefined) return '0.00';
            return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        },
        
        // Format order action to standard abbreviations
        formatAction(action) {
            if (!action) return '';
            
            // Handle both ORDERACTION. and OrderAction. prefixes
            const cleanAction = action.replace(/^(ORDERACTION\.|OrderAction\.)/, '');
            
            // Map to standard trading abbreviations
            const actionMap = {
                'SELL_TO_OPEN': 'STO',
                'BUY_TO_CLOSE': 'BTC',
                'BUY_TO_OPEN': 'BTO',
                'SELL_TO_CLOSE': 'STC',
                'EXPIRED': 'EXPIRED',
                'ASSIGNED': 'ASSIGNED',
                'EXERCISED': 'EXERCISED',
                'CASH_SETTLED': 'CASH_SETTLED'
            };
            
            return actionMap[cleanAction] || cleanAction;
        },
        
        // Format date
        formatDate(dateStr) {
            if (!dateStr) return '';
            // Parse as local date to avoid timezone shifts
            // dateStr format: "2025-05-20"
            const parts = dateStr.split('-');
            if (parts.length === 3) {
                // Create date as local time (month is 0-indexed)
                const date = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
                return date.toLocaleDateString('en-US', { 
                    year: 'numeric', 
                    month: 'short', 
                    day: 'numeric' 
                });
            }
            // Fallback for other formats
            return dateStr;
        },
        
        // Load dashboard data
        async loadDashboard() {
            try {
                console.log('Loading dashboard...');
                let url = '/api/dashboard';
                if (this.selectedAccount) {
                    url += `?account_number=${encodeURIComponent(this.selectedAccount)}`;
                }
                const response = await fetch(url);
                const data = await response.json();
                this.dashboard = data;
            } catch (error) {
                console.error('Error loading dashboard:', error);
            }
        },
        
        // Load trades
        
        // Load trade chains
        async loadChains() {
            this.chainsLoading = true;
            try {
                console.log('Loading chains...');
                const params = new URLSearchParams();
                if (this.selectedAccount) params.append('account_number', this.selectedAccount);
                if (this.filterUnderlying) params.append('underlying', this.filterUnderlying);
                
                const response = await fetch(`/api/chains?${params}`);
                const data = await response.json();
                this.chains = data.chains || [];
                
                // Sort chains by opening date descending (most recent first)
                this.chains.sort((a, b) => {
                    // If filtering by specific underlying, only sort by date
                    if (!this.filterUnderlying) {
                        // First sort by underlying for grouping when showing all
                        if (a.underlying !== b.underlying) {
                            return a.underlying.localeCompare(b.underlying);
                        }
                    }
                    // Then by opening date descending within each underlying
                    const dateA = new Date(a.opening_date || '1900-01-01');
                    const dateB = new Date(b.opening_date || '1900-01-01');
                    return dateB - dateA; // Descending order (most recent first)
                });
                
                console.log(`Loaded and sorted ${this.chains.length} chains`);
                this.applyStatusFilter(); // Apply status filtering after loading
                this.saveState(); // Save state when filters change
            } catch (error) {
                console.error('Error loading chains:', error);
            } finally {
                this.chainsLoading = false;
            }
        },
        
        // Apply status filtering to chains
        applyStatusFilter() {
            if (!this.showOpen && !this.showClosed) {
                // If both are unchecked, show nothing
                this.filteredChains = [];
            } else if (this.showOpen && this.showClosed) {
                // If both are checked, show all
                this.filteredChains = this.chains;
            } else if (this.showOpen) {
                // Show only open chains
                this.filteredChains = this.chains.filter(chain => chain.status === 'OPEN');
            } else if (this.showClosed) {
                // Show only closed chains
                this.filteredChains = this.chains.filter(chain => chain.status === 'CLOSED');
            }
        },
        
        // Load all available underlyings for the filter
        async loadAvailableUnderlyings() {
            try {
                // Fetch all chains without filters to get complete underlying list
                const params = new URLSearchParams();
                if (this.selectedAccount) params.append('account_number', this.selectedAccount);
                params.append('limit', '1000'); // Get more chains to ensure we see all underlyings
                
                const response = await fetch(`/api/chains?${params}`);
                const data = await response.json();
                const allChains = data.chains || [];
                
                // Extract unique underlyings
                const underlyings = [...new Set(allChains.map(chain => chain.underlying))];
                this.availableUnderlyings = underlyings.sort();
            } catch (error) {
                console.error('Error loading available underlyings:', error);
            }
        },
        
        // Manually render trades table (disabled - legacy trade system)
        renderTrades() {
            console.log('renderTrades called but disabled - using order chains display instead');
            return;
        },
        
        // Search chains (simplified - just filter locally for now)
        async searchTrades() {
            // For now, just reload chains (search functionality to be implemented later)
            await this.loadChains();
        },
        
        // Sync trades from Tastytrade
        async syncTrades() {
            this.syncing = true;
            try {
                console.log('Starting sync...');
                const response = await fetch('/api/sync', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({})
                });
                
                if (!response.ok) {
                    throw new Error(`Sync failed: ${response.statusText}`);
                }
                
                const result = await response.json();
                console.log('Sync completed:', result);
                
                // Reload data including accounts
                await this.loadAccounts();
                await this.loadDashboard();
                await this.loadChains();
                
                // Update last sync timestamp
                await this.loadLastSyncTimestamp();
                
            } catch (error) {
                console.error('Error syncing trades:', error);
                alert('Sync failed: ' + error.message);
            } finally {
                this.syncing = false;
            }
        },
        
        // Initial sync - rebuild entire database
        async initialSync() {
            const confirmed = confirm(
                'Initial Sync will CLEAR the entire database and rebuild it from scratch.\n\n' +
                'This will fetch all transactions from the last year and may take several minutes.\n\n' +
                'Are you sure you want to continue?'
            );
            
            if (!confirmed) return;
            
            this.initialSyncing = true;
            try {
                console.log('Starting initial sync...');
                const response = await fetch('/api/sync/initial', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`Initial sync failed: ${response.statusText}`);
                }
                
                const result = await response.json();
                console.log('Initial sync completed:', result);
                
                alert(`Initial sync completed successfully!\n\n` +
                      `Processed ${result.transactions_processed} transactions\n` +
                      `Created ${result.trades_saved} trades\n` +
                      `Updated ${result.positions_updated} positions`);
                
                // Reload all data including accounts
                await this.loadAccounts();
                await this.loadDashboard();
                await this.loadChains();
                
                // Update last sync timestamp
                await this.loadLastSyncTimestamp();
                
            } catch (error) {
                console.error('Error during initial sync:', error);
                alert('Initial sync failed: ' + error.message);
            } finally {
                this.initialSyncing = false;
            }
        },
        
        // Re-process chains from existing data
        async reprocessChains() {
            this.reprocessing = true;
            try {
                console.log('Starting chain reprocessing...');
                const response = await fetch('/api/reprocess-chains', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`Reprocessing failed: ${response.statusText}`);
                }
                
                const result = await response.json();
                console.log('Reprocessing completed:', result);
                
                // Reload chains and dashboard
                await this.loadDashboard();
                await this.loadChains();
                
            } catch (error) {
                console.error('Error during reprocessing:', error);
                alert('Reprocessing failed: ' + error.message);
            } finally {
                this.reprocessing = false;
            }
        },
        
        // Apply default sort without toggling
        applyDefaultSort() {
            // Sort trades array using current sortColumn and sortDirection
            this.trades.sort((a, b) => {
                let aVal = a[this.sortColumn];
                let bVal = b[this.sortColumn];
                
                // Handle numeric values
                if (this.sortColumn === 'current_pnl') {
                    aVal = aVal || 0;
                    bVal = bVal || 0;
                }
                
                // Handle dates
                if (this.sortColumn === 'entry_date' || this.sortColumn === 'exit_date') {
                    aVal = new Date(aVal || '1900-01-01');
                    bVal = new Date(bVal || '1900-01-01');
                }
                
                // Compare
                if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
                if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
                return 0;
            });
            
            // Re-render table
            this.renderTrades();
        },
        
        // Sort table
        sortTable(column) {
            // Toggle direction if same column
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                this.sortDirection = 'asc';
            }
            
            // Sort trades array
            this.trades.sort((a, b) => {
                let aVal = a[column];
                let bVal = b[column];
                
                // Handle numeric values
                if (column === 'current_pnl') {
                    aVal = aVal || 0;
                    bVal = bVal || 0;
                }
                
                // Handle dates
                if (column === 'entry_date' || column === 'exit_date') {
                    aVal = new Date(aVal || '1900-01-01');
                    bVal = new Date(bVal || '1900-01-01');
                }
                
                // Compare
                if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
                if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
                return 0;
            });
            
            // Re-render table
            this.renderTrades();
        },
        
        // Open edit modal (disabled - legacy trade system)
        openEditModal(tradeId) {
            alert('Trade editing is temporarily disabled. Feature will be restored for the order-based system.');
        },
        
        // Close edit modal
        closeEditModal() {
            console.log('Closing modal...');
            this.editModalOpen = false;
            this.editingTrade = null;
            document.getElementById('editModal').classList.add('hidden');
        },
        
        // Save trade changes (disabled - legacy trade system)
        async saveTradeChanges() {
            alert('Trade editing is temporarily disabled. Feature will be restored for the order-based system.');
        },
        
        // Open trade details modal (disabled - legacy trade system)
        async openTradeDetailsModal(tradeId) {
            alert('Trade details view is temporarily disabled. Feature will be restored for the order-based system.');
        },
        
        
        // Close trade details modal (legacy)
        closeTradeDetailsModal() {
            console.log('Closing trade details modal...');
            this.tradeDetailsModalOpen = false;
            this.tradeDetails = null;
            this.loadingTradeDetails = false;
            document.getElementById('tradeDetailsModal').classList.add('hidden');
        },
        
        // Save UI state to localStorage
        saveState() {
            const state = {
                selectedAccount: this.selectedAccount,
                filterUnderlying: this.filterUnderlying,
                filterStrategy: this.filterStrategy,
                filterStatus: this.filterStatus,
                syncDays: this.syncDays,
                sortColumn: this.sortColumn,
                sortDirection: this.sortDirection,
                showOpen: this.showOpen,
                showClosed: this.showClosed
            };
            localStorage.setItem('tradeJournalState', JSON.stringify(state));
        },
        
        // Get saved state from localStorage
        getSavedState() {
            try {
                const savedState = localStorage.getItem('tradeJournalState');
                return savedState ? JSON.parse(savedState) : null;
            } catch (error) {
                console.error('Error getting saved state:', error);
                return null;
            }
        },
        
        // Verify dropdown values are correctly set
        verifyDropdownValues() {
            // Check account dropdown
            const accountSelect = document.getElementById('account-select');
            if (accountSelect && this.selectedAccount) {
                accountSelect.value = this.selectedAccount;
                console.log('Account dropdown verified:', accountSelect.value);
            }
            
            // Check underlying dropdown  
            const underlyingSelects = document.querySelectorAll('[x-model="filterUnderlying"]');
            underlyingSelects.forEach(select => {
                if (this.filterUnderlying) {
                    select.value = this.filterUnderlying;
                    console.log('Underlying dropdown verified:', select.value);
                }
            });
            
        },
        
        // Load last sync timestamp
        async loadLastSyncTimestamp() {
            try {
                const response = await fetch('/api/sync/status');
                const data = await response.json();
                if (data.last_sync) {
                    // Format timestamp for display
                    const date = new Date(data.last_sync);
                    this.lastSyncTimestamp = date.toLocaleDateString('en-US', {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                } else {
                    this.lastSyncTimestamp = '';
                }
            } catch (error) {
                console.error('Error loading last sync timestamp:', error);
                this.lastSyncTimestamp = '';
            }
        },
        
        // Restore UI state from localStorage (legacy - still used by some code)
        restoreState() {
            const state = this.getSavedState();
            if (state) {
                // This is now handled in init(), but keep for compatibility
                console.log('restoreState called (legacy)');
            }
        }
    };
}

