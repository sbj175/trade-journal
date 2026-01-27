// Trade Journal Alpine.js Application - Fixed Version
function tradeJournal() {
    return {
        // State
        trades: [],
        chains: [],
        accounts: [],
        selectedAccount: '',
        availableUnderlyings: [],
        availableStrategies: [],
        username: null,
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
        timePeriod: 'all',  // 30, 60, 90, or 'all'
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

        // Initialization guard
        _initialized: false,

        // Initialize
        async init() {
            if (this._initialized) {
                console.log('Trade Journal already initialized, skipping...');
                return;
            }
            this._initialized = true;
            console.log('Initializing Trade Journal...');

            // Check authentication first
            try {
                const authResponse = await fetch('/api/auth/verify');
                if (!authResponse.ok) {
                    window.location.href = '/login';
                    return;
                }
                const authData = await authResponse.json();
                this.username = authData.username;
            } catch (error) {
                console.error('Auth check failed:', error);
                window.location.href = '/login';
                return;
            }

            // Get saved state before loading data
            const savedState = this.getSavedState();

            // Load accounts first
            await this.loadAccounts();

            // Check for URL parameters first (e.g., from positions page links)
            const urlParams = new URLSearchParams(window.location.search);
            const underlyingParam = urlParams.get('underlying');
            const accountParam = urlParams.get('account');

            // Determine final account to use (URL param takes priority over saved state)
            // Use null to indicate "not yet determined", empty string is valid for "All Accounts"
            let finalAccount = null;
            let accountDetermined = false;

            if (accountParam) {
                const accountExists = this.accounts.some(a => a.account_number === accountParam);
                if (accountExists) {
                    finalAccount = accountParam;
                    accountDetermined = true;
                    console.log('Applied URL parameter account filter:', accountParam);
                } else {
                    console.log('URL account parameter not found:', accountParam);
                }
            }

            // Fall back to shared account key first (synced across all pages)
            // Note: empty string means "All Accounts" was selected, which is valid
            if (!accountDetermined) {
                const sharedAccount = localStorage.getItem('trade_journal_selected_account');
                if (sharedAccount !== null) {
                    if (sharedAccount === '') {
                        // "All Accounts" was selected
                        finalAccount = '';
                        accountDetermined = true;
                        console.log('Restored "All Accounts" from shared key');
                    } else {
                        const accountExists = this.accounts.some(a => a.account_number === sharedAccount);
                        if (accountExists) {
                            finalAccount = sharedAccount;
                            accountDetermined = true;
                            console.log('Restored account from shared key:', sharedAccount);
                        } else {
                            console.log('Shared account not found:', sharedAccount);
                        }
                    }
                }
            }

            // Set the final account if determined
            if (accountDetermined) {
                this.selectedAccount = finalAccount;
            }

            // Load dashboard and underlyings once with final account
            await this.loadDashboard();
            await this.loadAvailableUnderlyings();
            
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
                this.timePeriod = savedState.timePeriod || 'all';
                this.sortColumn = savedState.sortColumn || 'underlying';
                this.sortDirection = savedState.sortDirection || 'asc';
                this.showOpen = savedState.showOpen !== undefined ? savedState.showOpen : true;
                this.showClosed = savedState.showClosed !== undefined ? savedState.showClosed : true;
                console.log('Restored other filters:', {
                    strategy: this.filterStrategy,
                    status: this.filterStatus,
                    timePeriod: this.timePeriod,
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
            const totalStartTime = performance.now();
            console.log('🕐 TIMING: Starting account change to:', this.selectedAccount);
            console.log('DEBUG: onAccountChange - this.selectedAccount is now:', this.selectedAccount);

            // Reset underlying filter when account changes
            const resetStartTime = performance.now();
            this.filterUnderlying = '';
            console.log('DEBUG: Reset underlying filter to All');
            this.saveState(); // Save state after resetting underlying
            const resetTime = performance.now() - resetStartTime;
            console.log(`🕐 TIMING: Filter reset took ${resetTime.toFixed(0)}ms`);

            const dashboardStartTime = performance.now();
            console.log('DEBUG: About to call loadDashboard()');
            await this.loadDashboard();
            console.log('DEBUG: loadDashboard() completed');
            const dashboardTime = performance.now() - dashboardStartTime;
            console.log(`🕐 TIMING: Dashboard completed in ${dashboardTime.toFixed(0)}ms`);

            const chainsStartTime = performance.now();
            console.log('DEBUG: About to call loadChains() with selectedAccount =', this.selectedAccount);
            await this.loadChains();
            console.log('DEBUG: loadChains() completed, this.chains.length =', this.chains.length);
            console.log('DEBUG: this.filteredChains.length =', this.filteredChains.length);
            const chainsTime = performance.now() - chainsStartTime;
            console.log(`🕐 TIMING: Chains completed in ${chainsTime.toFixed(0)}ms`);

            // Extract underlyings and strategies from loaded chains data (no additional API call needed)
            const extractStartTime = performance.now();
            const underlyings = [...new Set(this.chains.map(chain => chain.underlying))];
            this.availableUnderlyings = underlyings.sort();
            const strategies = [...new Set(this.chains.map(chain => chain.strategy_type || 'Unknown'))];
            this.availableStrategies = strategies.sort();
            const extractTime = performance.now() - extractStartTime;
            console.log(`🕐 TIMING: Underlyings and strategies extracted from chains in ${extractTime.toFixed(0)}ms (no API call)`);

            const totalTime = performance.now() - totalStartTime;
            console.log(`🕐 TIMING: *** TOTAL ACCOUNT CHANGE: ${totalTime.toFixed(0)}ms (${(totalTime/1000).toFixed(1)}s) ***`);
            console.log(`🕐 TIMING: Breakdown - Reset:${resetTime.toFixed(0)}ms, Dashboard:${dashboardTime.toFixed(0)}ms, Extract:${extractTime.toFixed(0)}ms, Chains:${chainsTime.toFixed(0)}ms`);
        },

        // Handle underlying filter change
        onUnderlyingChange() {
            this.saveState();
            this.loadChains();
        },

        // Handle strategy filter change
        onStrategyChange() {
            this.saveState();
            this.applyStatusFilter();
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
        
        // Get display quantity (negative for sell actions, positive for buy actions)
        getDisplayQuantity(position) {
            if (!position || typeof position.quantity === 'undefined') {
                return 0;
            }
            
            // Determine the current action for this position
            // If it has a closing_action, that's the current transaction being displayed
            // Otherwise, use the opening_action
            const currentAction = (position.closing_action || position.opening_action || '').toUpperCase();
            
            // SELL actions (STO, STC) should be negative, BUY actions (BTO, BTC) should be positive
            const isSellAction = currentAction.includes('SELL') || currentAction.includes('STC') || currentAction.includes('STO');
            
            // Return negative quantity for sell actions, positive for buy actions
            return isSellAction ? -Math.abs(position.quantity) : Math.abs(position.quantity);
        },
        
        // Helper function to determine the correct divisor for credit/debit calculation
        getCreditDebitDivisor(order) {
            if (!order || !order.positions || order.positions.length === 0) {
                return 0;
            }

            // For rolling orders, we have both closing (BTC/STC) and opening (BTO/STO) positions
            // A rolling order: BTC 2 + BTC 14 (close 16) + STO 2 + STO 14 (open 16) = 32 positions total
            // But the actual number of contracts is 16 (not 32), because opening and closing are part of the SAME roll
            // Use just the closing side (positions with closing_action or status CLOSED)

            // Helper function to normalize action strings
            const normalizeAction = (action) => {
                if (!action) return '';
                return action.replace('OrderAction.', '').toUpperCase();
            };

            // First, try to find positions that have a closing_action set (BTC/STC)
            const closingPositions = order.positions.filter(pos =>
                pos.closing_action && (pos.closing_action === 'BTC' || pos.closing_action === 'STC')
            );

            if (closingPositions.length > 0) {
                // Use the quantity from the first closing position (all legs in a spread have the same quantity)
                const closingQuantity = Math.abs(closingPositions[0].quantity || 0);
                if (closingQuantity > 0) {
                    console.log(`getCreditDebitDivisor(${order.order_id}): Found ${closingPositions.length} closing positions with closing_action, qty per spread=${closingQuantity}`);
                    return closingQuantity;
                }
            }

            // Second fallback: check opening_action for positions that are closing (opening_action shows BTC/STC for rolls)
            // Handle both "BTC" and "OrderAction.BUY_TO_CLOSE" formats
            const closingByAction = order.positions.filter(pos => {
                const normalizedAction = normalizeAction(pos.opening_action);
                return (normalizedAction === 'BTC' || normalizedAction === 'BUY_TO_CLOSE' ||
                        normalizedAction === 'STC' || normalizedAction === 'SELL_TO_CLOSE') &&
                       pos.status === 'CLOSED';
            });

            if (closingByAction.length > 0) {
                // Use the quantity from the first closing position (all legs in a spread have the same quantity)
                const closingQuantity = Math.abs(closingByAction[0].quantity || 0);
                if (closingQuantity > 0) {
                    console.log(`getCreditDebitDivisor(${order.order_id}): Found ${closingByAction.length} positions with closing actions, qty per spread=${closingQuantity}`);
                    return closingQuantity;
                }
            }

            // Third fallback: for opening orders, sum opening positions
            const openingPositions = order.positions.filter(pos => {
                const normalizedAction = normalizeAction(pos.opening_action);
                return (normalizedAction === 'BTO' || normalizedAction === 'BUY_TO_OPEN' ||
                        normalizedAction === 'STO' || normalizedAction === 'SELL_TO_OPEN') &&
                       pos.status !== 'CLOSED';
            });

            if (openingPositions.length > 0) {
                // Use the quantity from the first opening position (all legs in a spread have the same quantity)
                const openingQuantity = Math.abs(openingPositions[0].quantity || 0);
                if (openingQuantity > 0) {
                    console.log(`getCreditDebitDivisor(${order.order_id}): Found ${openingPositions.length} opening positions, qty per spread=${openingQuantity}`);
                    return openingQuantity;
                }
            }

            // Final fallback: use first position's quantity (legacy behavior)
            const fallback = Math.abs(order.positions[0].quantity || 0);
            console.log(`getCreditDebitDivisor(${order.order_id}): Using fallback qty=${fallback}, positions:`, order.positions.map(p => ({action: p.opening_action, closing: p.closing_action, qty: p.quantity, status: p.status})));
            return fallback;
        },
        
        // Calculate per-share credit/debit for rolling orders
        calculateRollCreditDebit(order) {
            if (!order || order.order_type !== 'ROLLING' || !order.positions || order.positions.length === 0) {
                return null;
            }
            
            // Use helper function to get the correct divisor (handles ratio spreads)
            const divisor = this.getCreditDebitDivisor(order);
            
            if (divisor === 0) {
                return null;
            }
            
            const orderPnL = order.total_pnl || 0;
            const perRatioAmount = Math.abs(orderPnL) / divisor / 100; // Divide by 100 to get per-share amount
            const isCredit = orderPnL > 0;
            
            return {
                amount: perRatioAmount,
                type: isCredit ? 'credit' : 'debit'
            };
        },
        
        // Format roll credit/debit for display
        formatRollCreditDebit(order) {
            const rollData = this.calculateRollCreditDebit(order);
            if (!rollData) return '';
            
            return `${rollData.amount.toFixed(2)} ${rollData.type}`;
        },
        
        // Calculate per-share credit/debit for opening orders
        calculateOpeningCreditDebit(order) {
            if (!order || order.order_type !== 'OPENING' || !order.positions || order.positions.length === 0) {
                return null;
            }
            
            // Use helper function to get the correct divisor (handles ratio spreads)
            const divisor = this.getCreditDebitDivisor(order);
            
            if (divisor === 0) {
                return null;
            }
            
            const orderPnL = order.total_pnl || 0;
            const perRatioAmount = Math.abs(orderPnL) / divisor / 100; // Divide by 100 to get per-share amount
            const isCredit = orderPnL > 0;
            
            return {
                amount: perRatioAmount,
                type: isCredit ? 'credit' : 'debit'
            };
        },
        
        // Format opening credit/debit for display
        formatOpeningCreditDebit(order) {
            const openingData = this.calculateOpeningCreditDebit(order);
            if (!openingData) return '';

            return `${openingData.amount.toFixed(2)} ${openingData.type}`;
        },

        // Calculate per-share credit/debit for closing orders
        calculateClosingCreditDebit(order) {
            if (!order || order.order_type !== 'CLOSING' || !order.positions || order.positions.length === 0) {
                return null;
            }

            // Use helper function to get the correct divisor (handles ratio spreads)
            const divisor = this.getCreditDebitDivisor(order);

            if (divisor === 0) {
                return null;
            }

            const orderPnL = order.total_pnl || 0;
            const perRatioAmount = Math.abs(orderPnL) / divisor / 100; // Divide by 100 to get per-share amount
            const isCredit = orderPnL > 0;

            return {
                amount: perRatioAmount,
                type: isCredit ? 'credit' : 'debit'
            };
        },

        // Format closing credit/debit for display
        formatClosingCreditDebit(order) {
            const closingData = this.calculateClosingCreditDebit(order);
            if (!closingData) return '';

            return `${closingData.amount.toFixed(2)} ${closingData.type}`;
        },

        // Load dashboard data
        async loadDashboard() {
            const startTime = performance.now();
            try {
                console.log('🕐 TIMING: Starting loadDashboard()');
                let url = '/api/dashboard';
                if (this.selectedAccount) {
                    url += `?account_number=${encodeURIComponent(this.selectedAccount)}`;
                }
                const fetchStart = performance.now();
                const response = await fetch(url);
                const data = await response.json();
                const fetchTime = performance.now() - fetchStart;
                // Merge the data instead of replacing to preserve filteredSummary
                this.dashboard = {
                    ...this.dashboard,
                    ...data,
                    filteredSummary: this.dashboard.filteredSummary || {
                        total_pnl: 0,
                        realized_pnl: 0,
                        unrealized_pnl: 0,
                        win_rate: 0,
                        open_chains: 0,
                        closed_chains: 0,
                        total_chains: 0
                    }
                };
                const totalTime = performance.now() - startTime;
                console.log(`🕐 TIMING: Dashboard loaded in ${totalTime.toFixed(0)}ms (fetch: ${fetchTime.toFixed(0)}ms)`);
            } catch (error) {
                console.error('Error loading dashboard:', error);
                const errorTime = performance.now() - startTime;
                console.log(`🕐 TIMING: Dashboard loading failed after ${errorTime.toFixed(0)}ms`);
            }
        },
        
        // Load trades
        
        // Load trade chains
        async loadChains() {
            const startTime = performance.now();
            this.chainsLoading = true;
            try {
                console.log('🕐 TIMING: Starting loadChains()');
                console.log('DEBUG: selectedAccount =', this.selectedAccount);
                console.log('DEBUG: filterUnderlying =', this.filterUnderlying);

                const params = new URLSearchParams();
                // Always pass account_number - empty string for "All Accounts", specific value for single account
                params.append('account_number', this.selectedAccount || '');
                if (this.filterUnderlying) params.append('underlying', this.filterUnderlying);

                const urlStr = `/api/chains?${params}`;
                console.log('DEBUG: Fetching from URL:', urlStr);

                const fetchStart = performance.now();
                const response = await fetch(urlStr);
                const data = await response.json();
                const fetchTime = performance.now() - fetchStart;
                console.log(`🕐 TIMING: API fetch took ${fetchTime.toFixed(0)}ms`);
                console.log('DEBUG: API response data:', data);
                console.log('DEBUG: API response chains count:', data.chains?.length || 0);

                this.chains = data.chains || [];
                console.log('DEBUG: Assigned to this.chains, length =', this.chains.length);
                
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
                console.log('DEBUG: After sorting, this.chains.length =', this.chains.length);

                const sortingStart = performance.now();
                this.applyStatusFilter(); // Apply status filtering after loading
                const sortingTime = performance.now() - sortingStart;
                console.log('DEBUG: After applyStatusFilter, this.filteredChains.length =', this.filteredChains.length);
                console.log('DEBUG: this.filteredChains =', this.filteredChains);

                const saveStateStart = performance.now();
                this.saveState(); // Save state when filters change
                const saveStateTime = performance.now() - saveStateStart;

                const totalTime = performance.now() - startTime;
                console.log(`🕐 TIMING: Total loadChains took ${totalTime.toFixed(0)}ms (fetch: ${fetchTime.toFixed(0)}ms, sorting: ${sortingTime.toFixed(0)}ms, saveState: ${saveStateTime.toFixed(0)}ms)`);
                console.log(`🕐 TIMING: Loaded and sorted ${this.chains.length} chains, filtered to ${this.filteredChains.length}`);

                // Log timing data from server if available
                if (data.timing) {
                    console.log(`🕐 TIMING: Server breakdown: total=${data.timing.total_time}s, db=${data.timing.db_time}s, v2=${data.timing.v2_time}s, format=${data.timing.format_time}s`);
                }
            } catch (error) {
                console.error('Error loading chains:', error);
                const errorTime = performance.now() - startTime;
                console.log(`🕐 TIMING: loadChains failed after ${errorTime.toFixed(0)}ms`);
            } finally {
                this.chainsLoading = false;
            }
        },
        
        // Apply status filtering to chains
        applyStatusFilter() {
            console.log('DEBUG: applyStatusFilter called');
            console.log('DEBUG: this.chains.length =', this.chains.length);
            console.log('DEBUG: this.showOpen =', this.showOpen, ', this.showClosed =', this.showClosed);

            let chains = this.chains;

            // Apply time period filtering first
            // Only applies to CLOSED chains (by closing_date). Open chains always shown.
            if (this.timePeriod && this.timePeriod !== 'all') {
                const days = parseInt(this.timePeriod);
                const cutoffDate = new Date();
                cutoffDate.setDate(cutoffDate.getDate() - days);
                // Format as YYYY-MM-DD string for comparison (avoids timezone issues)
                const cutoffStr = cutoffDate.toISOString().split('T')[0];
                const beforeCount = chains.length;
                chains = chains.filter(chain => {
                    // Open chains: always show (they're current positions)
                    if (chain.status === 'OPEN') return true;
                    // Closed chains: filter by closing_date (string comparison)
                    return chain.closing_date && chain.closing_date >= cutoffStr;
                });
                console.log('DEBUG: After time period filter (' + days + ' days, cutoff=' + cutoffStr + '), count =', chains.length, '(was', beforeCount, ')');
            }

            // Apply status filtering
            if (!this.showOpen && !this.showClosed) {
                // If both are unchecked, show nothing
                chains = [];
                console.log('DEBUG: Both showOpen and showClosed are false, chains set to []');
            } else if (this.showOpen && this.showClosed) {
                // If both are checked, show all (already filtered by time)
                console.log('DEBUG: Both showOpen and showClosed are true, showing all');
            } else if (this.showOpen) {
                // Show only open chains
                chains = chains.filter(chain => chain.status === 'OPEN');
                console.log('DEBUG: Filtered to OPEN chains, count =', chains.length);
            } else if (this.showClosed) {
                // Show only closed chains
                chains = chains.filter(chain => chain.status === 'CLOSED');
                console.log('DEBUG: Filtered to CLOSED chains, count =', chains.length);
            }

            // Apply strategy filtering if set
            if (this.filterStrategy) {
                const beforeCount = chains.length;
                chains = chains.filter(chain => {
                    const strategy = chain.strategy_type || 'Unknown';
                    return strategy === this.filterStrategy;
                });
                console.log('DEBUG: After strategy filter, count =', chains.length, '(was', beforeCount, ')');
            }

            // Force reactivity by creating a new array reference
            // This ensures Alpine.js detects the change
            console.log('DEBUG: Setting this.filteredChains to array of length', chains.length);
            this.filteredChains = [...chains];
            console.log('DEBUG: applyStatusFilter complete, this.filteredChains.length =', this.filteredChains.length);

            // Calculate filtered dashboard statistics
            this.calculateFilteredDashboard();
        },
        
        // Calculate dashboard statistics from filtered chains
        calculateFilteredDashboard() {
            const chains = this.filteredChains || [];

            // Calculate basic counts (from filtered chains for display)
            const openChains = chains.filter(chain => chain.status === 'OPEN');
            const closedChains = chains.filter(chain => chain.status === 'CLOSED');

            // Calculate P&L totals with proper handling of enhanced open chains vs closed chains
            let totalPnl = 0;
            let realizedPnl = 0;
            let unrealizedPnl = 0;

            chains.forEach(chain => {
                if (chain.status === 'OPEN' && chain.data_source === 'live_api') {
                    // For open chains with live data, use the unrealized P&L
                    totalPnl += (chain.unrealized_pnl || 0);
                    unrealizedPnl += (chain.unrealized_pnl || 0);
                } else {
                    // For closed chains or chains without live data, use total_pnl (realized)
                    totalPnl += (chain.total_pnl || 0);
                    realizedPnl += (chain.total_pnl || 0);
                }
            });

            // Calculate win rate from closed chains in the filtered set
            // This respects account, underlying, strategy, and time period filters but not open/closed toggle
            let chainsForWinRate = this.chains;

            // Apply time period filter (same logic as applyStatusFilter)
            // Only applies to closed chains (by closing_date). Open chains always included.
            if (this.timePeriod && this.timePeriod !== 'all') {
                const days = parseInt(this.timePeriod);
                const cutoffDate = new Date();
                cutoffDate.setDate(cutoffDate.getDate() - days);
                // Format as YYYY-MM-DD string for comparison (avoids timezone issues)
                const cutoffStr = cutoffDate.toISOString().split('T')[0];
                chainsForWinRate = chainsForWinRate.filter(chain => {
                    // Open chains: always include
                    if (chain.status === 'OPEN') return true;
                    // Closed chains: filter by closing_date (string comparison)
                    return chain.closing_date && chain.closing_date >= cutoffStr;
                });
            }

            // Apply strategy filter
            if (this.filterStrategy) {
                chainsForWinRate = chainsForWinRate.filter(chain => {
                    const strategy = chain.strategy_type || 'Unknown';
                    return strategy === this.filterStrategy;
                });
            }
            const closedChainsForWinRate = chainsForWinRate.filter(chain => chain.status === 'CLOSED');
            const profitableClosedChains = closedChainsForWinRate.filter(chain => chain.total_pnl >= 0);  // >= 0 to count scratch trades as wins
            const winRate = closedChainsForWinRate.length > 0 ? (profitableClosedChains.length / closedChainsForWinRate.length) * 100 : 0;
            
            // Update filtered summary
            this.dashboard.filteredSummary = {
                total_pnl: totalPnl,
                realized_pnl: realizedPnl,
                unrealized_pnl: unrealizedPnl,
                win_rate: winRate,
                open_chains: openChains.length,
                closed_chains: closedChains.length,
                total_chains: chains.length
            };
        },
        
        // Check if any filters are active (excluding status/open-closed toggle)
        hasActiveFilters() {
            return this.filterUnderlying !== '' ||
                   this.filterStrategy !== '' ||
                   this.selectedAccount !== '' ||
                   (this.timePeriod && this.timePeriod !== 'all');
        },

        // Check if status filters (open/closed toggle) are active
        hasStatusFilters() {
            return !(this.showOpen && this.showClosed);
        },
        
        // Load all available underlyings for the filter
        async loadAvailableUnderlyings() {
            const startTime = performance.now();
            console.log('🕐 TIMING: Starting loadAvailableUnderlyings()');
            try {
                // Fetch all chains without filters to get complete underlying list
                const params = new URLSearchParams();
                if (this.selectedAccount) params.append('account_number', this.selectedAccount);
                params.append('limit', '1000'); // Get more chains to ensure we see all underlyings

                const fetchStart = performance.now();
                const response = await fetch(`/api/chains?${params}`);
                const data = await response.json();
                const fetchTime = performance.now() - fetchStart;

                const processingStart = performance.now();
                const allChains = data.chains || [];

                // Extract unique underlyings and strategies
                const underlyings = [...new Set(allChains.map(chain => chain.underlying))];
                this.availableUnderlyings = underlyings.sort();
                const strategies = [...new Set(allChains.map(chain => chain.strategy_type || 'Unknown'))];
                this.availableStrategies = strategies.sort();
                const processingTime = performance.now() - processingStart;

                const totalTime = performance.now() - startTime;
                console.log(`🕐 TIMING: loadAvailableUnderlyings completed in ${totalTime.toFixed(0)}ms (fetch: ${fetchTime.toFixed(0)}ms, processing: ${processingTime.toFixed(0)}ms)`);
            } catch (error) {
                console.error('Error loading available underlyings:', error);
                const errorTime = performance.now() - startTime;
                console.log(`🕐 TIMING: loadAvailableUnderlyings failed after ${errorTime.toFixed(0)}ms`);
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
                timePeriod: this.timePeriod,
                syncDays: this.syncDays,
                sortColumn: this.sortColumn,
                sortDirection: this.sortDirection,
                showOpen: this.showOpen,
                showClosed: this.showClosed
            };
            localStorage.setItem('tradeJournalState', JSON.stringify(state));
            // Also save account to shared key (synced across all pages)
            localStorage.setItem('trade_journal_selected_account', this.selectedAccount || '');
        },

        // Handle time period change
        onTimePeriodChange() {
            this.saveState();
            this.applyStatusFilter();
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
        },
        
        // Helper method to get display quantity (negative for sell actions, positive for buy actions)
        getDisplayQuantity(position) {
            if (!position || typeof position.quantity === 'undefined') {
                return 0;
            }
            
            // Determine the current action for this position
            // If it has a closing_action, that's the current transaction being displayed
            // Otherwise, use the opening_action
            const currentAction = (position.closing_action || position.opening_action || '').toUpperCase();
            
            // SELL actions (STO, STC) should be negative, BUY actions (BTO, BTC) should be positive
            const isSellAction = currentAction.includes('SELL') || currentAction.includes('STC') || currentAction.includes('STO');
            
            // Return negative quantity for sell actions, positive for buy actions
            return isSellAction ? -Math.abs(position.quantity) : Math.abs(position.quantity);
        },

        async logout() {
            try {
                const response = await fetch('/api/auth/logout', { method: 'POST' });
                if (response.ok) {
                    // Logout successful, redirect to login page
                    window.location.href = '/login';
                } else {
                    console.error('Logout failed');
                }
            } catch (error) {
                console.error('Logout error:', error);
                // Force redirect to login page even if request fails
                window.location.href = '/login';
            }
        }
    };
}

