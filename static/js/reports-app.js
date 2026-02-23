document.addEventListener('alpine:init', () => {
    Alpine.data('reportsApp', () => ({
        // State
        accounts: [],
        selectedAccount: '',
        timePeriod: '90',
        loading: true,

        // Category-based filtering
        filterDirection: [],  // 'bullish', 'bearish', 'neutral'
        filterType: [],       // 'credit', 'debit'
        filterShares: false,

        // Sorting
        sortColumn: 'totalPnl',
        sortDirection: 'desc',

        // Report Data
        summary: {
            totalPnl: 0,
            totalTrades: 0,
            wins: 0,
            losses: 0,
            winRate: 0,
            avgPnl: 0,
            avgWin: 0,
            avgLoss: 0,
            largestWin: 0,
            largestLoss: 0,
            avgMaxRisk: 0,
            avgMaxReward: 0
        },
        strategyBreakdown: [],

        async init() {
            // Load accounts first
            await this.loadAccounts();

            // Then load saved filters (after accounts are loaded)
            this.loadSavedFilters();

            // Fetch initial report
            await this.fetchReport();
        },

        loadSavedFilters() {
            // Load saved account selection (shared across all pages)
            const savedAccount = localStorage.getItem('trade_journal_selected_account');
            if (savedAccount !== null) {
                this.selectedAccount = savedAccount;
            }

            // Load saved time period
            const savedTimePeriod = localStorage.getItem('reports_time_period');
            if (savedTimePeriod) {
                this.timePeriod = savedTimePeriod;
            }

            // Load saved category filters
            const savedFilters = localStorage.getItem('reports_category_filters');
            if (savedFilters) {
                try {
                    const parsed = JSON.parse(savedFilters);
                    this.filterDirection = parsed.direction || [];
                    this.filterType = parsed.type || [];
                    this.filterShares = parsed.shares || false;
                } catch (e) {
                    // Default: no filters (show all)
                }
            }

            // Load saved sort preference
            const savedSort = localStorage.getItem('reports_sort');
            if (savedSort) {
                try {
                    const parsed = JSON.parse(savedSort);
                    this.sortColumn = parsed.column || 'totalPnl';
                    this.sortDirection = parsed.direction || 'desc';
                } catch (e) {
                    // Default sort
                }
            }
        },

        saveFilters() {
            localStorage.setItem('reports_category_filters', JSON.stringify({
                direction: this.filterDirection,
                type: this.filterType,
                shares: this.filterShares
            }));
        },

        saveAccountSelection() {
            // Save to shared localStorage (synced across all pages)
            localStorage.setItem('trade_journal_selected_account', this.selectedAccount);
        },

        onAccountChange() {
            this.saveAccountSelection();
            this.fetchReport();
        },

        getAccountSymbol(accountNumber) {
            const account = this.accounts.find(a => a.account_number === accountNumber);
            if (!account) return '?';
            const name = (account.account_name || '').toUpperCase();
            if (name.includes('ROTH')) return 'R';
            if (name.includes('INDIVIDUAL')) return 'I';
            if (name.includes('TRADITIONAL')) return 'T';
            return name.charAt(0) || '?';
        },

        saveTimePeriod() {
            localStorage.setItem('reports_time_period', this.timePeriod);
        },

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
            this.saveFilters();
            this.fetchReport();
        },

        getActiveStrategies() {
            // Returns list of strategy names that match current filters
            const strategies = [];
            const noDirectionFilter = this.filterDirection.length === 0;
            const noTypeFilter = this.filterType.length === 0;

            for (const [strategy, cat] of Object.entries(STRATEGY_CATEGORIES)) {
                // Handle Shares separately
                if (cat.isShares) {
                    if (this.filterShares) {
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

        async loadAccounts() {
            try {
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
                        return 4;
                    };
                    return getAccountTypeOrder(a.account_name) - getAccountTypeOrder(b.account_name);
                });
            } catch (error) {
                console.error('Error loading accounts:', error);
            }
        },

        async fetchReport() {
            this.loading = true;

            try {
                const params = new URLSearchParams();
                if (this.selectedAccount) {
                    params.append('account_number', this.selectedAccount);
                }
                params.append('days', this.timePeriod);

                // Get strategies based on category filters
                const activeStrategies = this.getActiveStrategies();
                params.append('strategies', activeStrategies.join(','));

                const response = await fetch(`/api/reports/performance?${params}`);
                const data = await response.json();

                if (data.error) {
                    console.error('Report error:', data.error);
                    return;
                }

                this.summary = data.summary || this.summary;
                this.strategyBreakdown = data.breakdown || [];

                // Apply current sort
                this.applySortToBreakdown();

            } catch (error) {
                console.error('Error fetching report:', error);
            } finally {
                this.loading = false;
            }
        },

        // Sort the strategy breakdown table
        sortBreakdown(column) {
            // Toggle direction if same column
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                // Default to descending for numeric columns, ascending for strategy name
                this.sortDirection = column === 'strategy' ? 'asc' : 'desc';
            }

            this.applySortToBreakdown();

            // Save sort preference
            localStorage.setItem('reports_sort', JSON.stringify({
                column: this.sortColumn,
                direction: this.sortDirection
            }));
        },

        // Apply current sort to breakdown array
        applySortToBreakdown() {
            this.strategyBreakdown.sort((a, b) => {
                let aVal = a[this.sortColumn];
                let bVal = b[this.sortColumn];

                // Handle string columns
                if (this.sortColumn === 'strategy') {
                    aVal = (aVal || '').toLowerCase();
                    bVal = (bVal || '').toLowerCase();
                } else {
                    // Numeric columns
                    aVal = aVal || 0;
                    bVal = bVal || 0;
                }

                // Compare
                if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1;
                if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1;
                return 0;
            });
        },

        formatPercent(value) {
            if (value === null || value === undefined) return '0.0';
            return value.toFixed(1);
        },

    }));
});
