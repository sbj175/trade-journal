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

        // Sync notification
        syncNotification: null,
        syncNotificationTimeout: null,
        
        // Filters
        searchTerm: '',
        filterStatus: '',
        filterUnderlying: '',
        timePeriod: 'all',  // 'today', 'yesterday', 7, 30, 60, 90, or 'all'
        showOpen: true,
        showClosed: true,
        filteredChains: [],

        // Direct chain_id filter (from position page link)
        filterChainId: '',

        // Category-based filtering (like Reports page)
        filterDirection: [],  // 'bullish', 'bearish', 'neutral'
        filterType: [],       // 'credit', 'debit'

        // Strategy to category mapping
        strategyCategories: {
            'Bull Put Spread': { direction: 'bullish', type: 'credit' },
            'Bear Call Spread': { direction: 'bearish', type: 'credit' },
            'Iron Condor': { direction: 'neutral', type: 'credit' },
            'Iron Butterfly': { direction: 'neutral', type: 'credit' },
            'Cash Secured Put': { direction: 'bullish', type: 'credit' },
            'Covered Call': { direction: 'bullish', type: 'credit' },
            'Short Put': { direction: 'bullish', type: 'credit' },
            'Short Call': { direction: 'bearish', type: 'credit' },
            'Short Strangle': { direction: 'neutral', type: 'credit' },
            'Short Straddle': { direction: 'neutral', type: 'credit' },
            'Bull Call Spread': { direction: 'bullish', type: 'debit' },
            'Bear Put Spread': { direction: 'bearish', type: 'debit' },
            'Long Call': { direction: 'bullish', type: 'debit' },
            'Long Put': { direction: 'bearish', type: 'debit' },
            'Long Strangle': { direction: 'neutral', type: 'debit' },
            'Long Straddle': { direction: 'neutral', type: 'debit' },
            'Shares': { direction: null, type: null, isShares: true }
        },
        
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

        // Order comments (server-persisted)
        orderComments: {},
        _commentSaveTimers: {},

        // Position notes (server-persisted)
        positionNotes: {},
        _noteSaveTimers: {},

        // Live quotes state for Chains page
        underlyingQuotes: {},
        quoteUpdateCounter: 0,
        liveQuotesActive: false,
        lastQuoteUpdate: null,
        ws: null,

        // Initialize
        async init() {
            if (this._initialized) {
                console.log('Trade Journal already initialized, skipping...');
                return;
            }
            this._initialized = true;
            console.log('Initializing Trade Journal...');

            // Get saved state before loading data
            const savedState = this.getSavedState();

            // Load accounts first
            await this.loadAccounts();

            // Check for URL parameters first (e.g., from positions page links)
            const urlParams = new URLSearchParams(window.location.search);
            const underlyingParam = urlParams.get('underlying');
            const accountParam = urlParams.get('account');
            const statusParam = urlParams.get('status');
            const chainIdParam = urlParams.get('chain_id');

            // Handle chain_id parameter (direct link from positions page)
            if (chainIdParam) {
                this.filterChainId = chainIdParam;
                this.showOpen = true;
                this.showClosed = true;
                this.filterUnderlying = '';
                this.timePeriod = 'all';
                console.log('Applied URL parameter chain_id filter:', chainIdParam);
            }

            // Handle status parameter (e.g., from positions page linking to open chains)
            if (statusParam === 'open') {
                this.showOpen = true;
                this.showClosed = false;
                console.log('Applied URL parameter status filter: open only');
            }

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
            if (underlyingParam || accountParam || statusParam || chainIdParam) {
                window.history.replaceState({}, document.title, window.location.pathname);
            }
            
            // Apply saved underlying if no URL parameter was provided
            // Skip when chain_id is set — we want an unfiltered view for direct chain lookup
            if (!underlyingParam && !chainIdParam) {
                const sharedUnderlying = localStorage.getItem('trade_journal_selected_underlying') || '';
                if (sharedUnderlying) {
                    this.filterUnderlying = sharedUnderlying;
                    console.log('Restored underlying from shared key:', sharedUnderlying);
                }
            }
            
            // Apply other saved filters
            if (savedState) {
                // Clear category filters when navigating via URL param
                // (user explicitly wants to see that specific chain/symbol regardless of category)
                const clearCategoryFilters = underlyingParam || chainIdParam;
                this.filterDirection = clearCategoryFilters ? [] : (savedState.filterDirection || []);
                this.filterType = clearCategoryFilters ? [] : (savedState.filterType || []);
                this.filterStatus = chainIdParam ? '' : (savedState.filterStatus || '');
                this.timePeriod = chainIdParam ? 'all' : (savedState.timePeriod || 'all');
                this.sortColumn = savedState.sortColumn || 'underlying';
                this.sortDirection = savedState.sortDirection || 'asc';
                // Only apply saved state for showOpen/showClosed if no URL status/chain_id param
                if (!statusParam && !chainIdParam) {
                    this.showOpen = savedState.showOpen !== undefined ? savedState.showOpen : true;
                    this.showClosed = savedState.showClosed !== undefined ? savedState.showClosed : true;
                }
                console.log('Restored other filters:', {
                    direction: this.filterDirection,
                    type: this.filterType,
                    status: this.filterStatus,
                    timePeriod: this.timePeriod,
                    showOpen: this.showOpen,
                    showClosed: this.showClosed
                });
            }
            
            // Load trades and chains with restored filters
            await this.loadChains();

            // Load order comments and position notes from server
            await this.loadOrderComments();
            await this.loadPositionNotes();

            // Load cached quotes and initialize WebSocket for live data
            await this.loadCachedQuotes();
            this.initializeWebSocket();

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

            // Preserve current underlying filter to check if it exists in new account
            const previousUnderlying = this.filterUnderlying;

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

            // Only reset underlying filter if it doesn't exist in the new account
            if (previousUnderlying && !this.availableUnderlyings.includes(previousUnderlying)) {
                this.filterUnderlying = '';
                console.log('DEBUG: Reset underlying filter - symbol not found in new account');
            }
            this.saveState();

            const totalTime = performance.now() - totalStartTime;
            console.log(`🕐 TIMING: *** TOTAL ACCOUNT CHANGE: ${totalTime.toFixed(0)}ms (${(totalTime/1000).toFixed(1)}s) ***`);
            console.log(`🕐 TIMING: Breakdown - Dashboard:${dashboardTime.toFixed(0)}ms, Chains:${chainsTime.toFixed(0)}ms, Extract:${extractTime.toFixed(0)}ms`);
        },

        // Handle underlying filter change
        onUnderlyingChange() {
            this.saveState();
            this.loadChains();
        },

        // Toggle category filter (direction or type)
        toggleFilter(category, value) {
            if (category === 'direction') {
                const idx = this.filterDirection.indexOf(value);
                if (idx >= 0) {
                    this.filterDirection.splice(idx, 1);
                } else {
                    this.filterDirection.push(value);
                }
            } else if (category === 'type') {
                // Credit and Debit are mutually exclusive
                const idx = this.filterType.indexOf(value);
                if (idx >= 0) {
                    // Clicking an active button deselects it
                    this.filterType.splice(idx, 1);
                } else {
                    // Selecting one clears the other
                    this.filterType = [value];
                }
            }
            this.saveState();
            this.applyStatusFilter();
        },

        // Get list of strategies that match current category filters
        getActiveStrategies() {
            const strategies = [];
            const noDirectionFilter = this.filterDirection.length === 0;
            const noTypeFilter = this.filterType.length === 0;

            for (const [strategy, cat] of Object.entries(this.strategyCategories)) {
                // Handle Shares separately (always include if no filters)
                if (cat.isShares) {
                    if (noDirectionFilter && noTypeFilter) {
                        strategies.push(strategy);
                    }
                    continue;
                }

                // Check if strategy matches filters
                const directionMatch = noDirectionFilter || this.filterDirection.includes(cat.direction);
                const typeMatch = noTypeFilter || this.filterType.includes(cat.type);

                if (directionMatch && typeMatch) {
                    strategies.push(strategy);
                }
            }

            return strategies;
        },

        // Check if a chain's strategy matches the current category filters
        chainMatchesCategoryFilters(chain) {
            const strategy = chain.strategy_type || 'Unknown';
            const noDirectionFilter = this.filterDirection.length === 0;
            const noTypeFilter = this.filterType.length === 0;

            // If no filters are active, show all
            if (noDirectionFilter && noTypeFilter) {
                return true;
            }

            // Look up strategy category
            const cat = this.strategyCategories[strategy];

            // If strategy is not in our mapping, include it only if no filters are active
            if (!cat) {
                return noDirectionFilter && noTypeFilter;
            }

            // Handle Shares specially
            if (cat.isShares) {
                return noDirectionFilter && noTypeFilter;
            }

            // Check if strategy matches filters
            const directionMatch = noDirectionFilter || this.filterDirection.includes(cat.direction);
            const typeMatch = noTypeFilter || this.filterType.includes(cat.type);

            return directionMatch && typeMatch;
        },

        // Format number with commas
        formatNumber(num) {
            if (num === null || num === undefined) return '0.00';
            return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        },

        formatChainDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' });
        },

        // Format order date as "1/23 2:11p"
        formatOrderDate(isoString) {
            if (!isoString) return '';
            const d = new Date(isoString);
            const month = d.getMonth() + 1;
            const day = d.getDate();
            let hours = d.getHours();
            const minutes = d.getMinutes().toString().padStart(2, '0');
            const ampm = hours >= 12 ? 'p' : 'a';
            hours = hours % 12 || 12;
            return `${month}/${day} ${hours}:${minutes}${ampm}`;
        },

        // Get cutoff date string for time period filtering
        getTimePeriodDates(timePeriod) {
            const today = new Date();
            let cutoffDate = new Date();
            let exactDate = false;

            if (timePeriod === 'today') {
                // Match exact date for today
                exactDate = true;
            } else if (timePeriod === 'yesterday') {
                // Match exact date for yesterday
                cutoffDate.setDate(today.getDate() - 1);
                exactDate = true;
            } else {
                // Numeric days: 7, 30, 60, 90
                const days = parseInt(timePeriod);
                cutoffDate.setDate(today.getDate() - days);
            }

            // Format as YYYY-MM-DD string for comparison (avoids timezone issues)
            const cutoffStr = cutoffDate.toISOString().split('T')[0];
            return { cutoffStr, exactDate };
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

            // For rolls, use OPENING quantity (the new position size)
            // When a roll changes position size (e.g., closes 2, opens 1), the credit/debit
            // per share should be normalized to the NEW position size, not the old.
            // Example: ORCL roll collects $907, closes 2, opens 1 -> $907 ÷ 1 ÷ 100 = $9.07/share
            const normalizeAction = (action) => {
                if (!action) return '';
                return action.replace('OrderAction.', '').toUpperCase();
            };

            const openingPositions = order.positions.filter(pos => {
                const action = normalizeAction(pos.opening_action);
                return action === 'BTO' || action === 'BUY_TO_OPEN' ||
                       action === 'STO' || action === 'SELL_TO_OPEN';
            });

            const divisor = openingPositions.length > 0
                ? Math.abs(openingPositions[0].quantity || 0)
                : this.getCreditDebitDivisor(order); // fallback to original logic

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

        // Get current open positions for a chain
        // Aggregates across all orders to find positions that are still open
        getCurrentOpenPositions(chain) {
            if (!chain || !chain.orders || chain.status !== 'OPEN') {
                return [];
            }

            // Track positions by a unique key (symbol + strike + expiration + option_type)
            const positionMap = new Map();

            // Process all orders chronologically (oldest first)
            const sortedOrders = [...chain.orders].sort((a, b) =>
                new Date(a.order_date || 0) - new Date(b.order_date || 0)
            );

            for (const order of sortedOrders) {
                if (!order.positions) continue;

                for (const pos of order.positions) {
                    // Create a unique key for this position
                    const key = `${pos.symbol || ''}_${pos.strike || ''}_${pos.expiration || ''}_${pos.option_type || ''}`;

                    // Determine if this is opening or closing based on action
                    const action = (pos.opening_action || '').toUpperCase().replace('ORDERACTION.', '');
                    const isOpening = action.includes('BTO') || action.includes('STO') ||
                                      action.includes('BUY_TO_OPEN') || action.includes('SELL_TO_OPEN');
                    const isClosing = action.includes('BTC') || action.includes('STC') ||
                                      action.includes('BUY_TO_CLOSE') || action.includes('SELL_TO_CLOSE');

                    // Check for assignment/exercise/expiration closures
                    const closingAction = (pos.closing_action || '').toUpperCase();
                    const isAssignedOrExpired = closingAction.includes('ASSIGNED') ||
                                                closingAction.includes('EXERCISED') ||
                                                closingAction.includes('EXPIRED');

                    if (isOpening) {
                        // Opening: add to position or create new
                        const qty = Math.abs(pos.quantity || 0);
                        const isShort = action.includes('STO') || action.includes('SELL_TO_OPEN');

                        if (positionMap.has(key)) {
                            const existing = positionMap.get(key);
                            existing.quantity += isShort ? -qty : qty;
                            // Average the entry price (weighted)
                            const totalQty = Math.abs(existing.quantity);
                            if (totalQty > 0) {
                                existing.entry_price = ((existing.entry_price * (totalQty - qty)) +
                                                       (pos.opening_price * qty)) / totalQty;
                            }
                        } else {
                            positionMap.set(key, {
                                symbol: pos.symbol,
                                underlying: pos.underlying,
                                option_type: pos.option_type,
                                strike: pos.strike,
                                expiration: pos.expiration,
                                quantity: isShort ? -qty : qty,
                                entry_price: pos.opening_price || 0,
                                instrument_type: pos.instrument_type
                            });
                        }

                        // If this opening position was later closed (has closing_action), reduce it
                        if (isAssignedOrExpired && positionMap.has(key)) {
                            const existing = positionMap.get(key);
                            if (existing.quantity > 0) {
                                existing.quantity -= qty;
                            } else {
                                existing.quantity += qty;
                            }
                        }
                    } else if (isClosing) {
                        // Closing: reduce position
                        const qty = Math.abs(pos.quantity || 0);
                        if (positionMap.has(key)) {
                            const existing = positionMap.get(key);
                            // Closing reduces the absolute position
                            if (existing.quantity > 0) {
                                existing.quantity -= qty;
                            } else {
                                existing.quantity += qty;
                            }
                        }
                    }
                }
            }

            // Filter to only positions with non-zero quantity
            const openPositions = [];
            for (const [key, pos] of positionMap) {
                if (pos.quantity !== 0) {
                    openPositions.push(pos);
                }
            }

            // Sort by strike price
            openPositions.sort((a, b) => (a.strike || 0) - (b.strike || 0));

            return openPositions;
        },

        // Format position description for display
        formatPositionDescription(pos) {
            if (!pos.option_type) {
                return pos.symbol || 'Unknown';
            }
            const strike = pos.strike ? `$${pos.strike}` : '';
            const exp = pos.expiration || '';
            const type = pos.option_type || '';
            return `${strike} ${type} ${exp}`.trim();
        },

        // Format expiration date in short format (e.g., "Feb 27")
        formatExpirationShort(expiration) {
            if (!expiration) return '';
            const date = new Date(expiration + 'T00:00:00');
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            return `${months[date.getMonth()]} ${date.getDate()}`;
        },

        // Calculate days to expiration
        calculateDTE(expiration) {
            if (!expiration) return 0;
            const expDate = new Date(expiration + 'T00:00:00');
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const diffTime = expDate - today;
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            return Math.max(0, diffDays);
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
                if (this.filterChainId) params.append('chain_id', this.filterChainId);
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

                // Auto-expand when navigating to a specific chain
                if (this.filterChainId && this.filteredChains.length === 1) {
                    this.filteredChains[0].expanded = true;
                    console.log('Auto-expanded single chain result for chain_id:', this.filterChainId);
                }
                // Clear filterChainId after first load so subsequent loads are unfiltered
                if (this.filterChainId) {
                    this.filterChainId = '';
                }

                const saveStateStart = performance.now();
                this.saveState(); // Save state when filters change
                const saveStateTime = performance.now() - saveStateStart;

                const totalTime = performance.now() - startTime;
                console.log(`🕐 TIMING: Total loadChains took ${totalTime.toFixed(0)}ms (fetch: ${fetchTime.toFixed(0)}ms, sorting: ${sortingTime.toFixed(0)}ms, saveState: ${saveStateTime.toFixed(0)}ms)`);
                console.log(`🕐 TIMING: Loaded and sorted ${this.chains.length} chains, filtered to ${this.filteredChains.length}`);

                // Log timing data from server if available
                if (data.timing) {
                    console.log(`🕐 TIMING: Server breakdown: total=${data.timing.total_time}s, db=${data.timing.db_time}s, processor=${data.timing.processor_time}s, format=${data.timing.format_time}s`);
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
                const { cutoffStr, exactDate } = this.getTimePeriodDates(this.timePeriod);
                const beforeCount = chains.length;
                chains = chains.filter(chain => {
                    // Open chains: always show (they're current positions)
                    if (chain.status === 'OPEN') return true;
                    // Closed chains: filter by closing_date
                    if (!chain.closing_date) return false;
                    if (exactDate) {
                        // For "today" and "yesterday", match exact date
                        return chain.closing_date === cutoffStr;
                    }
                    // For day ranges, use >= comparison
                    return chain.closing_date >= cutoffStr;
                });
                console.log('DEBUG: After time period filter (' + this.timePeriod + ', cutoff=' + cutoffStr + ', exact=' + exactDate + '), count =', chains.length, '(was', beforeCount, ')');
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

            // Apply category-based filtering (direction and type)
            if (this.filterDirection.length > 0 || this.filterType.length > 0) {
                const beforeCount = chains.length;
                chains = chains.filter(chain => this.chainMatchesCategoryFilters(chain));
                console.log('DEBUG: After category filter (direction=' + this.filterDirection.join(',') + ', type=' + this.filterType.join(',') + '), count =', chains.length, '(was', beforeCount, ')');
            }

            // Force reactivity by creating a new array reference
            // This ensures Alpine.js detects the change
            console.log('DEBUG: Setting this.filteredChains to array of length', chains.length);
            this.filteredChains = [...chains];

            // Apply current sort order
            this.applySortToChains();

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
                const { cutoffStr, exactDate } = this.getTimePeriodDates(this.timePeriod);
                chainsForWinRate = chainsForWinRate.filter(chain => {
                    // Open chains: always include
                    if (chain.status === 'OPEN') return true;
                    // Closed chains: filter by closing_date
                    if (!chain.closing_date) return false;
                    if (exactDate) {
                        return chain.closing_date === cutoffStr;
                    }
                    return chain.closing_date >= cutoffStr;
                });
            }

            // Apply category filter
            if (this.filterDirection.length > 0 || this.filterType.length > 0) {
                chainsForWinRate = chainsForWinRate.filter(chain => this.chainMatchesCategoryFilters(chain));
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
                   this.filterDirection.length > 0 ||
                   this.filterType.length > 0 ||
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

                // Show sync notification
                this.showSyncNotification(result);

            } catch (error) {
                console.error('Error syncing trades:', error);
                alert('Sync failed: ' + error.message);
            } finally {
                this.syncing = false;
            }
        },

        // Show sync result notification
        showSyncNotification(result) {
            // Clear any existing timeout
            if (this.syncNotificationTimeout) {
                clearTimeout(this.syncNotificationTimeout);
            }

            this.syncNotification = {
                transactions: result.transactions_processed || 0,
                positions: result.positions_updated || 0,
                message: result.message || 'Sync completed'
            };

            // Auto-dismiss after 5 seconds
            this.syncNotificationTimeout = setTimeout(() => {
                this.dismissSyncNotification();
            }, 5000);
        },

        // Dismiss sync notification
        dismissSyncNotification() {
            this.syncNotification = null;
            if (this.syncNotificationTimeout) {
                clearTimeout(this.syncNotificationTimeout);
                this.syncNotificationTimeout = null;
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
                      `Processed ${result.transactions_processed || 0} transactions\n` +
                      `Created ${result.orders_saved || 0} orders in ${result.chains_saved || 0} chains\n` +
                      `Updated ${result.positions_updated || 0} positions`);
                
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
        
        // Sort table (legacy)
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

        // Sort chains - used by chains-dense.html
        sortChains(column) {
            // Toggle direction if same column
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                // Default to descending for dates, P&L/value columns, and price/ivr
                if (column === 'opening_date' || column === 'closing_date' || column === 'total_pnl' || column === 'net_liquidity' || column === 'total_value' || column === 'price' || column === 'ivr') {
                    this.sortDirection = 'desc';
                } else if (column === 'dte') {
                    // DTE defaults to ascending (nearest expiration first)
                    this.sortDirection = 'asc';
                } else {
                    this.sortDirection = 'asc';
                }
            }

            // Sort filteredChains array
            this.filteredChains.sort((a, b) => {
                let aVal, bVal;

                // Handle calculated total_value column (net_liq + realized for open chains)
                if (column === 'total_value') {
                    aVal = a.status === 'OPEN' ? ((a.net_liquidity || 0) + (a.total_pnl || 0)) : (a.total_pnl || 0);
                    bVal = b.status === 'OPEN' ? ((b.net_liquidity || 0) + (b.total_pnl || 0)) : (b.total_pnl || 0);
                } else if (column === 'price') {
                    // Get price from quotes, closed chains get null (sort to end)
                    const aQuote = a.status === 'OPEN' ? this.getUnderlyingQuote(a.underlying) : null;
                    const bQuote = b.status === 'OPEN' ? this.getUnderlyingQuote(b.underlying) : null;
                    aVal = aQuote ? aQuote.price : null;
                    bVal = bQuote ? bQuote.price : null;
                } else if (column === 'ivr') {
                    // Get IVR from quotes, closed chains get null (sort to end)
                    aVal = a.status === 'OPEN' ? this.getUnderlyingIVR(a.underlying) : null;
                    bVal = b.status === 'OPEN' ? this.getUnderlyingIVR(b.underlying) : null;
                } else if (column === 'dte') {
                    // Get min DTE, closed chains get null (sort to end)
                    aVal = this.getChainMinDTE(a);
                    bVal = this.getChainMinDTE(b);
                } else {
                    aVal = a[column];
                    bVal = b[column];
                }

                // Handle null values - push to end
                if (aVal === null && bVal === null) return 0;
                if (aVal === null) return 1;
                if (bVal === null) return -1;

                // Handle string columns
                if (column === 'underlying' || column === 'strategy_type' || column === 'status') {
                    aVal = (aVal || '').toLowerCase();
                    bVal = (bVal || '').toLowerCase();
                }

                // Handle numeric columns
                if (column === 'order_count' || column === 'cost_basis_per_share' || column === 'total_pnl' || column === 'net_liquidity' || column === 'total_value' || column === 'price' || column === 'ivr' || column === 'dte') {
                    aVal = aVal || 0;
                    bVal = bVal || 0;
                }

                // Handle date columns
                if (column === 'opening_date' || column === 'closing_date') {
                    aVal = aVal ? new Date(aVal) : new Date('1900-01-01');
                    bVal = bVal ? new Date(bVal) : new Date('1900-01-01');
                }

                // Compare
                if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
                if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
                return 0;
            });

            // Save state to persist sort preference
            this.saveState();
        },

        // Apply current sort to chains without toggling direction
        applySortToChains() {
            const column = this.sortColumn;
            const direction = this.sortDirection;

            this.filteredChains.sort((a, b) => {
                let aVal, bVal;

                // Handle calculated total_value column (net_liq + realized for open chains)
                if (column === 'total_value') {
                    aVal = a.status === 'OPEN' ? ((a.net_liquidity || 0) + (a.total_pnl || 0)) : (a.total_pnl || 0);
                    bVal = b.status === 'OPEN' ? ((b.net_liquidity || 0) + (b.total_pnl || 0)) : (b.total_pnl || 0);
                } else if (column === 'price') {
                    // Get price from quotes, closed chains get null (sort to end)
                    const aQuote = a.status === 'OPEN' ? this.getUnderlyingQuote(a.underlying) : null;
                    const bQuote = b.status === 'OPEN' ? this.getUnderlyingQuote(b.underlying) : null;
                    aVal = aQuote ? aQuote.price : null;
                    bVal = bQuote ? bQuote.price : null;
                } else if (column === 'ivr') {
                    // Get IVR from quotes, closed chains get null (sort to end)
                    aVal = a.status === 'OPEN' ? this.getUnderlyingIVR(a.underlying) : null;
                    bVal = b.status === 'OPEN' ? this.getUnderlyingIVR(b.underlying) : null;
                } else if (column === 'dte') {
                    // Get min DTE, closed chains get null (sort to end)
                    aVal = this.getChainMinDTE(a);
                    bVal = this.getChainMinDTE(b);
                } else {
                    aVal = a[column];
                    bVal = b[column];
                }

                // Handle null values - push to end
                if (aVal === null && bVal === null) return 0;
                if (aVal === null) return 1;
                if (bVal === null) return -1;

                // Handle string columns
                if (column === 'underlying' || column === 'strategy_type' || column === 'status') {
                    aVal = (aVal || '').toLowerCase();
                    bVal = (bVal || '').toLowerCase();
                }

                // Handle numeric columns
                if (column === 'order_count' || column === 'cost_basis_per_share' || column === 'total_pnl' || column === 'net_liquidity' || column === 'total_value' || column === 'price' || column === 'ivr' || column === 'dte') {
                    aVal = aVal || 0;
                    bVal = bVal || 0;
                }

                // Handle date columns
                if (column === 'opening_date' || column === 'closing_date') {
                    aVal = aVal ? new Date(aVal) : new Date('1900-01-01');
                    bVal = bVal ? new Date(bVal) : new Date('1900-01-01');
                }

                // Compare
                if (aVal < bVal) return direction === 'asc' ? -1 : 1;
                if (aVal > bVal) return direction === 'asc' ? 1 : -1;
                return 0;
            });
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
                filterDirection: this.filterDirection,
                filterType: this.filterType,
                filterStatus: this.filterStatus,
                timePeriod: this.timePeriod,
                syncDays: this.syncDays,
                sortColumn: this.sortColumn,
                sortDirection: this.sortDirection,
                showOpen: this.showOpen,
                showClosed: this.showClosed
            };
            localStorage.setItem('tradeJournalState', JSON.stringify(state));
            // Also save to shared keys (synced across all pages)
            localStorage.setItem('trade_journal_selected_account', this.selectedAccount || '');
            localStorage.setItem('trade_journal_selected_underlying', this.filterUnderlying || '');
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

        // Get single-letter account symbol (R=Roth, I=Individual, T=Traditional)
        getAccountSymbol(accountNumber) {
            const account = this.accounts.find(a => a.account_number === accountNumber);
            if (!account) return '?';
            const name = (account.account_name || '').toUpperCase();
            if (name.includes('ROTH')) return 'R';
            if (name.includes('INDIVIDUAL')) return 'I';
            if (name.includes('TRADITIONAL')) return 'T';
            return name.charAt(0) || '?';  // First letter fallback
        },

        // ===== Live Quotes for Chains Page =====

        // Initialize WebSocket connection for live quotes
        initializeWebSocket() {
            if (this.ws) {
                this.ws.close();
            }

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/quotes`;

            console.log('Connecting to WebSocket:', wsUrl);

            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected - LIVE');
                this.liveQuotesActive = true;
                this.requestLiveQuotes();
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    // Handle bulk quotes update: { "type": "quotes", "data": { "AAPL": {...}, ... } }
                    if (data.type === 'quotes' && data.data) {
                        for (const [symbol, quote] of Object.entries(data.data)) {
                            if (quote) {
                                this.underlyingQuotes[symbol] = {
                                    price: quote.price || quote.mark,
                                    change: quote.change,
                                    changePercent: quote.changePercent || quote.change_percent,
                                    ivr: quote.ivr || quote.ivPercentile || quote.iv_percentile,
                                    timestamp: Date.now()
                                };
                            }
                        }
                        this.quoteUpdateCounter++;
                        this.lastQuoteUpdate = new Date();
                        console.log('WebSocket received quotes for:', Object.keys(data.data).length, 'symbols');
                    }
                } catch (e) {
                    console.error('Error parsing WebSocket message:', e);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.liveQuotesActive = false;
                // Attempt to reconnect after 5 seconds
                setTimeout(() => {
                    if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
                        this.initializeWebSocket();
                    }
                }, 5000);
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.liveQuotesActive = false;
            };
        },

        // Request live quotes for open chain underlyings
        requestLiveQuotes() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return;
            }

            // Get unique underlyings from open chains
            const openChains = this.chains.filter(c => c.status === 'OPEN');
            const symbols = [...new Set(openChains.map(c => c.underlying))];

            if (symbols.length > 0) {
                console.log('Requesting quotes for symbols:', symbols);
                this.ws.send(JSON.stringify({
                    subscribe: symbols
                }));
            }
        },

        // Load cached quotes via REST API
        async loadCachedQuotes() {
            try {
                // Get unique underlyings from open chains
                const openChains = this.chains.filter(c => c.status === 'OPEN');
                const symbols = [...new Set(openChains.map(c => c.underlying))];

                if (symbols.length === 0) {
                    return;
                }

                console.log('Loading cached quotes for:', symbols);
                const response = await fetch(`/api/quotes?symbols=${symbols.join(',')}`);
                if (response.ok) {
                    const quotes = await response.json();
                    // API returns quotes directly: { "AAPL": {...}, "MSFT": {...} }
                    if (quotes && typeof quotes === 'object') {
                        for (const [symbol, quote] of Object.entries(quotes)) {
                            if (quote) {
                                this.underlyingQuotes[symbol] = {
                                    price: quote.price || quote.mark,
                                    change: quote.change,
                                    changePercent: quote.changePercent || quote.change_percent,
                                    ivr: quote.ivr || quote.ivPercentile || quote.iv_percentile,
                                    timestamp: Date.now()
                                };
                            }
                        }
                        this.quoteUpdateCounter++;
                        console.log('Loaded cached quotes:', Object.keys(quotes).length);
                    }
                }
            } catch (error) {
                console.error('Error loading cached quotes:', error);
            }
        },

        // Get quote data for an underlying symbol
        getUnderlyingQuote(underlying) {
            // Force reactivity by reading the counter
            const _ = this.quoteUpdateCounter;
            return this.underlyingQuotes[underlying] || null;
        },

        // Get IVR as integer (0-100) for an underlying
        getUnderlyingIVR(underlying) {
            const quote = this.getUnderlyingQuote(underlying);
            if (quote && quote.ivr !== undefined && quote.ivr !== null) {
                // API returns IVR as decimal (0.0-1.0), convert to percentage (0-100)
                const ivr = quote.ivr <= 1 ? quote.ivr * 100 : quote.ivr;
                return Math.round(ivr);
            }
            return null;
        },

        // Load order comments from server
        async loadOrderComments() {
            try {
                const response = await fetch('/api/order-comments');
                if (response.ok) {
                    const data = await response.json();
                    this.orderComments = data.comments || {};
                } else {
                    this.orderComments = {};
                }
            } catch (error) {
                console.error('Error loading order comments:', error);
                this.orderComments = {};
            }
        },

        // Get comment for a specific order
        getOrderComment(order) {
            return this.orderComments[order.order_id] || '';
        },

        // Update comment for a specific order (debounced save to server)
        updateOrderComment(order, value) {
            const key = order.order_id;
            this.orderComments[key] = value;

            // Clear existing timer for this order
            if (this._commentSaveTimers[key]) {
                clearTimeout(this._commentSaveTimers[key]);
            }

            // Debounce: save after 500ms of no typing
            this._commentSaveTimers[key] = setTimeout(() => {
                fetch(`/api/order-comments/${encodeURIComponent(order.order_id)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ comment: value })
                }).catch(err => console.error('Error saving order comment:', err));
                delete this._commentSaveTimers[key];
            }, 500);
        },

        // Position notes (server-persisted)
        async loadPositionNotes() {
            try {
                const response = await fetch('/api/position-notes');
                if (response.ok) {
                    const data = await response.json();
                    this.positionNotes = data.notes || {};
                } else {
                    this.positionNotes = {};
                }
            } catch (error) {
                console.error('Error loading position notes:', error);
                this.positionNotes = {};
            }
        },

        getPositionNote(chain) {
            const chainKey = 'chain_' + chain.chain_id;
            return this.positionNotes[chainKey] || '';
        },

        updatePositionNote(chain, value) {
            const key = 'chain_' + chain.chain_id;
            this.positionNotes[key] = value;
            if (this._noteSaveTimers[key]) {
                clearTimeout(this._noteSaveTimers[key]);
            }
            this._noteSaveTimers[key] = setTimeout(() => {
                fetch(`/api/position-notes/${encodeURIComponent(key)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note: value })
                }).catch(err => console.error('Error saving position note:', err));
                delete this._noteSaveTimers[key];
            }, 500);
        },

        // Calculate minimum DTE across all open positions in a chain
        getChainMinDTE(chain) {
            if (!chain || chain.status !== 'OPEN') {
                return null;
            }

            const openPositions = this.getCurrentOpenPositions(chain);
            if (openPositions.length === 0) {
                return null;
            }

            let minDTE = Infinity;
            for (const pos of openPositions) {
                if (pos.expiration) {
                    const dte = this.calculateDTE(pos.expiration);
                    if (dte < minDTE) {
                        minDTE = dte;
                    }
                }
            }

            return minDTE === Infinity ? null : minDTE;
        }
    };
}

