function buildOptionStratUrl(strategyType, underlying, legs) {
    const SLUGS = {
        'Bull Put Spread':  'bull-put-spread',
        'Bull Call Spread':  'bull-call-spread',
        'Bear Put Spread':  'bear-put-spread',
        'Bear Call Spread':  'bear-call-spread',
    };
    const slug = SLUGS[strategyType];
    if (!slug || !underlying || !legs || legs.length !== 2) return null;
    if (legs.some(l => !l.expiration || !l.option_type || l.strike == null)) return null;

    const encodeLeg = (leg) => {
        const sign = leg.isShort ? '-' : '';
        const d = leg.expiration.replace(/-/g, '').slice(2, 8);
        const type = leg.option_type.toUpperCase().startsWith('P') ? 'P' : 'C';
        const strike = leg.strike % 1 === 0 ? String(Math.trunc(leg.strike)) : String(leg.strike);
        return `${sign}.${underlying}${d}${type}${strike}`;
    };

    return `https://optionstrat.com/build/${slug}/${underlying}/${legs.map(encodeLeg).join(',')}`;
}

document.addEventListener('alpine:init', () => {
    Alpine.data('positionsApp', () => ({
        // State
        allChains: [],        // chain objects from /api/open-chains
        allItems: [],         // flat list of displayable items (chains)
        filteredItems: [],
        accounts: [],
        accountBalances: {},
        underlyingQuotes: {},
        quoteUpdateCounter: 0,
        positionComments: {},
        _noteSaveTimers: {},
        selectedAccount: '',
        selectedUnderlying: '',
        isLoading: false,
        error: null,
        liveQuotesActive: false,
        lastQuoteUpdate: null,
        lastSyncTimestamp: '',
        ws: null,
        // Roll analysis state
        strategyTargets: {},
        rollAlertSettings: { enabled: true, profitTarget: true, lossLimit: true, lateStage: true, deltaSaturation: true, lowRewardToRisk: true },
        privacyMode: 'off',

        // Reconciliation state
        reconciliation: null,

        // Sorting state
        sortColumn: 'underlying',
        sortDirection: 'asc',

        // Computed properties
        get currentAccountBalance() {
            if (!this.selectedAccount || this.selectedAccount === '') {
                const values = Object.values(this.accountBalances);
                if (values.length === 0) return null;
                return values.reduce((acc, balance) => ({
                    cash_balance: (acc.cash_balance || 0) + (balance.cash_balance || 0),
                    derivative_buying_power: (acc.derivative_buying_power || 0) + (balance.derivative_buying_power || 0),
                    equity_buying_power: (acc.equity_buying_power || 0) + (balance.equity_buying_power || 0),
                    net_liquidating_value: (acc.net_liquidating_value || 0) + (balance.net_liquidating_value || 0)
                }), { cash_balance: 0, derivative_buying_power: 0, equity_buying_power: 0, net_liquidating_value: 0 });
            }
            return this.accountBalances[this.selectedAccount] || null;
        },

        get groupedPositions() {
            try {
                if (this.isLoading || !this.filteredItems || this.filteredItems.length === 0) return [];

                // Each chain/share item IS already a group — no grouping logic needed
                // Just apply sorting
                this.quoteUpdateCounter; // ensure recompute on quote changes
                const self = this;

                const sorted = [...this.filteredItems].sort((a, b) => {
                    let aVal, bVal;

                    switch (self.sortColumn) {
                        case 'underlying':
                            aVal = a.underlying.toLowerCase();
                            bVal = b.underlying.toLowerCase();
                            break;
                        case 'ivr':
                            aVal = self.getUnderlyingIVR(a.underlying) ?? -1;
                            bVal = self.getUnderlyingIVR(b.underlying) ?? -1;
                            break;
                        case 'price':
                            const aQuote = self.underlyingQuotes[a.underlying];
                            const bQuote = self.underlyingQuotes[b.underlying];
                            aVal = aQuote?.price || 0;
                            bVal = bQuote?.price || 0;
                            break;
                        case 'cost_basis':
                            aVal = self.getGroupCostBasis(a);
                            bVal = self.getGroupCostBasis(b);
                            break;
                        case 'net_liq':
                            aVal = self.getGroupNetLiqWithLiveQuotes(a);
                            bVal = self.getGroupNetLiqWithLiveQuotes(b);
                            break;
                        case 'pnl':
                        case 'total_pnl':
                            aVal = self.getGroupTotalPnL(a);
                            bVal = self.getGroupTotalPnL(b);
                            break;
                        case 'realized_pnl':
                            aVal = a.realized_pnl || 0;
                            bVal = b.realized_pnl || 0;
                            break;
                        case 'open_pnl':
                            aVal = self.getGroupOpenPnL(a);
                            bVal = self.getGroupOpenPnL(b);
                            break;
                        case 'pnl_percent':
                            aVal = parseFloat(self.getGroupPnLPercent(a)) || 0;
                            bVal = parseFloat(self.getGroupPnLPercent(b)) || 0;
                            break;
                        case 'days':
                            aVal = self.getGroupDaysOpen(a) || 0;
                            bVal = self.getGroupDaysOpen(b) || 0;
                            break;
                        case 'dte':
                            aVal = self.getMinDTE(a) ?? 9999;
                            bVal = self.getMinDTE(b) ?? 9999;
                            break;
                        case 'strategy':
                            aVal = self.getGroupStrategyLabel(a).toLowerCase();
                            bVal = self.getGroupStrategyLabel(b).toLowerCase();
                            break;
                        default:
                            aVal = a.underlying.toLowerCase();
                            bVal = b.underlying.toLowerCase();
                    }

                    if (aVal < bVal) return self.sortDirection === 'asc' ? -1 : 1;
                    if (aVal > bVal) return self.sortDirection === 'asc' ? 1 : -1;
                    return 0;
                });

                // Attach roll analysis to each group for reactive badge display
                sorted.forEach(group => {
                    group.rollAnalysis = this.getRollAnalysis(group);
                });

                // Phase 3: Insert subtotal rows when sorted by underlying
                if (this.sortColumn === 'underlying') {
                    return this._insertSubtotals(sorted);
                }
                return sorted;
            } catch (error) {
                console.error('Error in groupedPositions:', error);
                return [];
            }
        },

        get underlyings() {
            return [...new Set(this.filteredItems.map(item => item.underlying).filter(s => s && s !== 'Unknown'))];
        },

        // Initialize
        async init() {
            await Auth.requireAuth();
            await Auth.requireTastytrade();
            await this.loadComments();
            this.loadRollAlertSettings();
            this.privacyMode = localStorage.getItem('privacyMode') || 'off';
            await this.fetchAccounts();
            await this.loadStrategyTargets();
            this.loadFilterPreferences();
            await this.loadAccountBalances();
            await this.fetchPositions();
            await this.loadCachedQuotes();
            this.initializeWebSocket();
        },

        async fetchAccounts() {
            try {
                const response = await Auth.authFetch('/api/accounts');
                const data = await response.json();
                this.accounts = data.accounts || [];
                this.accounts.sort((a, b) => {
                    const getOrder = (name) => {
                        const n = (name || '').toUpperCase();
                        if (n.includes('ROTH')) return 1;
                        if (n.includes('INDIVIDUAL')) return 2;
                        if (n.includes('TRADITIONAL')) return 3;
                        return 4;
                    };
                    return getOrder(a.account_name) - getOrder(b.account_name);
                });
            } catch (error) { console.error('Failed to load accounts:', error); }
        },

        async fetchPositions(includeSync = false) {
            this.isLoading = true;
            this.error = null;
            try {
                if (includeSync) {
                    const syncResp = await Auth.authFetch('/api/sync', { method: 'POST' });
                    if (syncResp.ok) {
                        const syncData = await syncResp.json();
                        if (syncData.reconciliation) {
                            this.reconciliation = syncData.reconciliation;
                        }
                    }
                }

                // Fetch from chain-based endpoint
                const response = await Auth.authFetch('/api/open-chains');
                const data = await response.json();

                this.allChains = [];
                this.allItems = [];

                if (typeof data === 'object' && !Array.isArray(data)) {
                    Object.entries(data).forEach(([accountNumber, accountData]) => {
                        const chains = accountData.chains || [];

                        chains.forEach(chain => {
                            chain.account_number = accountNumber;
                            this.allChains.push(chain);

                            this.allItems.push({
                                ...chain,
                                groupKey: `${accountNumber}|${chain.chain_id}`,
                                displayKey: chain.underlying,
                                accountNumber: accountNumber,
                                positions: chain.open_legs || [],
                                equityLegs: chain.equity_legs || [],
                                equitySummary: chain.equity_summary || null,
                            });
                        });
                    });
                }
                // Migrate comment keys from chain_ to group_ prefix
                this._migrateCommentKeys();

                this.applyFilters();
            } catch (error) {
                console.error('Failed to load positions:', error);
                this.error = 'Failed to load positions';
            } finally {
                this.isLoading = false;
            }
        },

        async loadAccountBalances() {
            try {
                const response = await Auth.authFetch('/api/account-balances');
                const data = await response.json();
                const balances = data.balances || data;
                this.accountBalances = {};
                if (Array.isArray(balances)) {
                    balances.forEach(balance => { this.accountBalances[balance.account_number] = balance; });
                }
            } catch (error) { console.error('Failed to load account balances:', error); }
        },

        async loadCachedQuotes() {
            try {
                const symbols = this._collectSymbols();
                if (symbols.length === 0) return;

                const response = await Auth.authFetch(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`);
                if (response.ok) {
                    const quotes = await response.json();
                    for (const [symbol, quoteData] of Object.entries(quotes)) {
                        if (quoteData && typeof quoteData === 'object') {
                            this.underlyingQuotes[symbol] = {
                                ...this.underlyingQuotes[symbol],
                                ...quoteData
                            };
                        }
                    }
                    this.lastQuoteUpdate = new Date().toLocaleTimeString();
                    this.quoteUpdateCounter++;
                }
            } catch (error) { console.error('Error loading cached quotes:', error); }
        },

        _collectSymbols() {
            const symbolSet = new Set();
            this.filteredItems.forEach(item => {
                // Add underlying
                if (item.underlying) symbolSet.add(item.underlying);
                // Add option leg symbols
                (item.positions || []).forEach(leg => {
                    if (leg.symbol) symbolSet.add(leg.symbol);
                });
            });
            return Array.from(symbolSet).filter(s => s && s !== 'Unknown');
        },

        async initializeWebSocket() {
            try {
                const wsUrl = await Auth.getAuthenticatedWsUrl('/ws/quotes');
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    this.liveQuotesActive = true;
                    this.requestLiveQuotes();
                };

                this.ws.onmessage = (event) => {
                    const message = JSON.parse(event.data);
                    if (message.type === 'quotes' && message.data) {
                        let quotesUpdated = false;
                        for (const [symbol, quoteData] of Object.entries(message.data)) {
                            if (quoteData && typeof quoteData === 'object') {
                                this.underlyingQuotes[symbol] = {
                                    ...this.underlyingQuotes[symbol],
                                    ...quoteData
                                };
                                quotesUpdated = true;
                            }
                        }
                        if (quotesUpdated) {
                            this.underlyingQuotes = { ...this.underlyingQuotes };
                        }
                        this.quoteUpdateCounter++;
                        this.lastQuoteUpdate = new Date().toLocaleTimeString();
                    }
                };

                this.ws.onclose = () => {
                    this.liveQuotesActive = false;
                    setTimeout(() => this.initializeWebSocket(), 5000);
                };
            } catch (error) { console.error('WebSocket error:', error); }
        },

        requestLiveQuotes() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            const symbols = this._collectSymbols();
            if (symbols.length > 0) {
                this.ws.send(JSON.stringify({ subscribe: symbols }));
            }
        },

        applyFilters() {
            this.filteredItems = this.allItems.filter(item => {
                if (this.selectedAccount && item.accountNumber !== this.selectedAccount) return false;
                if (this.selectedUnderlying) {
                    if (item.underlying !== this.selectedUnderlying) return false;
                }
                return true;
            });

            if (this.selectedAccount && this.filteredItems.length === 0 && this.allItems.length > 0) {
                this.selectedAccount = '';
                this.filteredItems = this.allItems.filter(item => {
                    if (this.selectedUnderlying) {
                        if (item.underlying !== this.selectedUnderlying) return false;
                    }
                    return true;
                });
            }
        },

        filterPositions() { this.applyFilters(); },

        saveFilterPreferences() {
            localStorage.setItem('trade_journal_selected_account', this.selectedAccount || '');
            localStorage.setItem('trade_journal_selected_underlying', this.selectedUnderlying || '');
        },

        loadFilterPreferences() {
            const savedAccount = localStorage.getItem('trade_journal_selected_account');
            if (savedAccount !== null) this.selectedAccount = savedAccount;

            const savedUnderlying = localStorage.getItem('trade_journal_selected_underlying');
            if (savedUnderlying) this.selectedUnderlying = savedUnderlying;

            const savedSort = localStorage.getItem('positions_sort');
            if (savedSort) {
                try {
                    const parsed = JSON.parse(savedSort);
                    this.sortColumn = parsed.column || 'underlying';
                    this.sortDirection = parsed.direction || 'asc';
                } catch (e) { /* Default sort */ }
            }
        },

        async onAccountChange() {
            this.applyFilters();
            this.saveFilterPreferences();
            await this.loadCachedQuotes();
            this.requestLiveQuotes();
        },

        // Utility methods
        // Format dollar amounts: drop decimals for large numbers to prevent overflow
        formatDollar(value) {
            const abs = Math.abs(value || 0);
            return formatNumber(abs, abs >= 100000 ? 0 : 2);
        },
        // Return smaller font class for very large dollar amounts
        dollarSizeClass(value) {
            return Math.abs(value || 0) >= 1000000 ? 'text-xs' : '';
        },

        // ===== P&L CALCULATIONS =====
        // Group = a chain item or share item from allItems

        getGroupCostBasis(group) {
            if (group._isSubtotal) return group._subtotalCostBasis;
            const optionTotal = (group.positions || []).reduce((s, l) => s + (l.cost_basis || 0), 0);
            const equityTotal = (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0);
            return optionTotal + equityTotal;
        },

        // Open P/L: unrealized P&L on current legs (net_liq - cost_basis)
        getGroupOpenPnL(group) {
            this.quoteUpdateCounter;
            if (group._isSubtotal) return group._subtotalOpenPnL;
            const optionPnL = (group.positions || []).reduce((sum, leg) => sum + this._calculateLegPnL(leg), 0);
            const eqLegs = group.equityLegs || [];
            if (eqLegs.length === 0) return optionPnL;
            const eqCost = eqLegs.reduce((s, l) => s + (l.cost_basis || 0), 0);
            const eqMV = this._calculateEquityMarketValue(group);
            return optionPnL + eqMV + eqCost;
        },

        // Realized P/L: banked P&L from rolls/partial closes
        getGroupRealizedPnL(group) {
            if (group._isSubtotal) return group._subtotalRealizedPnL;
            return group.realized_pnl || 0;
        },

        // Total P/L = Realized + Open
        getGroupTotalPnL(group) {
            if (group._isSubtotal) return group._subtotalTotalPnL;
            return this.getGroupRealizedPnL(group) + this.getGroupOpenPnL(group);
        },

        getGroupNetLiqWithLiveQuotes(group) {
            this.quoteUpdateCounter;
            if (group._isSubtotal) return group._subtotalNetLiq;
            const optionMV = (group.positions || []).reduce((sum, leg) => sum + this._calculateLegMarketValue(leg), 0);
            const equityMV = this._calculateEquityMarketValue(group);
            return optionMV + equityMV;
        },

        getGroupPnLPercent(group) {
            const costBasis = this.getGroupCostBasis(group);
            const openPnL = this.getGroupOpenPnL(group);
            if (costBasis === 0) return null;
            return ((openPnL / Math.abs(costBasis)) * 100).toFixed(1);
        },

        getGroupDaysOpen(group) {
            if (group._isSubtotal) return null;
            const openDate = group.opening_date;
            if (!openDate) return null;
            const d = new Date(openDate + 'T00:00:00');
            const now = new Date();
            const days = Math.floor((now - d) / (1000 * 60 * 60 * 24));
            return days > 0 ? days : 0;
        },

        getMinDTE(group) {
            if (group._isSubtotal) return null;
            const legs = group.positions || [];
            let minDTE = null;
            for (const leg of legs) {
                if (leg.expiration) {
                    const dateStr = leg.expiration.substring(0, 10);
                    const expDate = new Date(dateStr + 'T00:00:00');
                    const today = new Date();
                    today.setHours(0, 0, 0, 0);
                    const dte = Math.ceil((expDate - today) / (1000 * 60 * 60 * 24));
                    if (minDTE === null || dte < minDTE) minDTE = dte;
                }
            }
            return minDTE;
        },

        // ===== Live P&L for individual legs =====
        _calculateLegMarketValue(leg) {
            this.quoteUpdateCounter;
            const optionSymbol = (leg.symbol || '').trim();
            const optionQuote = this.underlyingQuotes[optionSymbol];
            if (optionQuote && optionQuote.mark !== undefined) {
                const absValue = optionQuote.mark * leg.quantity * 100;
                return leg.quantity_direction === 'Short' ? -absValue : absValue;
            }
            // Fallback: use opening price
            const absValue = (leg.opening_price || 0) * leg.quantity * 100;
            return leg.quantity_direction === 'Short' ? -absValue : absValue;
        },

        _calculateLegPnL(leg) {
            const marketValue = this._calculateLegMarketValue(leg);
            const costBasis = leg.cost_basis || 0;
            const absMV = Math.abs(marketValue);
            const absCB = Math.abs(costBasis);
            if (leg.quantity_direction === 'Short') {
                return absCB - absMV;
            } else {
                return absMV - absCB;
            }
        },

        _hasEquity(group) {
            return (group.equityLegs || []).length > 0;
        },
        _isEquityOnly(group) {
            return this._hasEquity(group) && (group.positions || []).length === 0;
        },
        _calculateEquityMarketValue(group) {
            const eqLegs = group.equityLegs || [];
            if (eqLegs.length === 0) return 0;
            const quote = this.underlyingQuotes[group.underlying];
            if (!quote || !quote.price) return 0;
            let total = 0;
            eqLegs.forEach(leg => {
                const signed = leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity;
                total += quote.price * signed;
            });
            return total;
        },

        // ===== Sort =====
        sortPositions(column) {
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                if (['pnl', 'total_pnl', 'realized_pnl', 'open_pnl', 'pnl_percent', 'net_liq', 'price', 'ivr'].includes(column)) {
                    this.sortDirection = 'desc';
                } else {
                    this.sortDirection = 'asc';
                }
            }
            localStorage.setItem('positions_sort', JSON.stringify({
                column: this.sortColumn,
                direction: this.sortDirection
            }));
        },

        getGroupStrategyLabel(group) {
            if (group._isSubtotal) return '';
            if (group.strategy_type && group.strategy_type !== 'Unknown') return group.strategy_type;
            return 'Unknown';
        },

        getOptionStratUrl(group) {
            if (!group.strategy_type || !group.underlying) return null;
            const optionLegs = (group.positions || []).filter(l =>
                l.instrument_type && l.instrument_type.includes('OPTION'));
            if (optionLegs.length !== 2) return null;
            const legs = optionLegs.map(l => ({
                expiration: l.expiration,
                option_type: l.option_type,
                strike: l.strike,
                isShort: l.quantity_direction === 'Short',
            }));
            return buildOptionStratUrl(group.strategy_type, group.underlying, legs);
        },

        // ===== Leg display helpers =====
        getOptionType(leg) {
            if (leg.option_type === 'Call' || leg.option_type === 'C') return 'C';
            if (leg.option_type === 'Put' || leg.option_type === 'P') return 'P';
            if (leg.option_type) return leg.option_type.charAt(0).toUpperCase();
            const match = (leg.symbol || '').match(/\d{6}([CP])/);
            if (match) return match[1];
            return '—';
        },
        getSignedQuantity(leg) {
            const qty = leg.quantity || 0;
            if (leg.quantity_direction === 'Short') return -qty;
            return qty;
        },
        getExpirationDate(leg) {
            if (!leg.expiration) return '';
            const dateStr = leg.expiration.substring(0, 10);
            const date = new Date(dateStr + 'T00:00:00');
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        },
        getStrikePrice(leg) {
            if (leg.strike && leg.strike > 0) return parseFloat(leg.strike.toFixed(2)).toString();
            const symbol = leg.symbol || '';
            const match = symbol.match(/([CP])(\d+)/);
            if (match && match[2].length >= 3) {
                return parseFloat(parseFloat(match[2].slice(0, -3) + '.' + match[2].slice(-3)).toFixed(2)).toString();
            }
            return '';
        },
        getDTE(leg) {
            if (!leg.expiration) return null;
            const dateStr = leg.expiration.substring(0, 10);
            const expDate = new Date(dateStr + 'T00:00:00');
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const dte = Math.ceil((expDate - today) / (1000 * 60 * 60 * 24));
            return dte;
        },

        getUnderlyingQuote(underlying) {
            return this.underlyingQuotes[underlying] || null;
        },
        getUnderlyingIVR(underlying) {
            const quote = this.getUnderlyingQuote(underlying);
            if (!quote || !quote.ivr) return null;
            return Math.round(quote.ivr * 100);
        },

        // ===== Phase 3: Subtotals =====
        _insertSubtotals(sorted) {
            // Group items by underlying+account, insert subtotal rows for multi-item groups
            const result = [];
            let currentKey = null;
            let currentGroup = [];

            const flushGroup = () => {
                if (currentGroup.length <= 1) {
                    result.push(...currentGroup);
                    return;
                }
                // Build subtotal row
                const underlying = currentGroup[0].underlying;
                const acct = currentGroup[0].accountNumber;
                const subtotal = {
                    _isSubtotal: true,
                    groupKey: `subtotal_${acct}_${underlying}`,
                    displayKey: underlying,
                    underlying: underlying,
                    accountNumber: acct,
                    _subtotalCostBasis: 0,
                    _subtotalNetLiq: 0,
                    _subtotalOpenPnL: 0,
                    _subtotalRealizedPnL: 0,
                    _subtotalTotalPnL: 0,
                    _childCount: currentGroup.length,
                };
                currentGroup.forEach(item => {
                    subtotal._subtotalCostBasis += this.getGroupCostBasis(item);
                    subtotal._subtotalNetLiq += this.getGroupNetLiqWithLiveQuotes(item);
                    subtotal._subtotalOpenPnL += this.getGroupOpenPnL(item);
                    subtotal._subtotalRealizedPnL += this.getGroupRealizedPnL(item);
                    subtotal._subtotalTotalPnL += this.getGroupTotalPnL(item);
                });
                result.push(subtotal);
                result.push(...currentGroup);
            };

            for (const item of sorted) {
                const key = `${item.accountNumber}|${item.underlying}`;
                if (key !== currentKey) {
                    if (currentGroup.length > 0) flushGroup();
                    currentKey = key;
                    currentGroup = [item];
                } else {
                    currentGroup.push(item);
                }
            }
            if (currentGroup.length > 0) flushGroup();
            return result;
        },

        // ===== Roll Analysis (works on option legs) =====
        getRollAnalysis(group) {
            const strategy = this.getGroupStrategyLabel(group);
            const supportedStrategies = ['Bull Call Spread', 'Bear Put Spread', 'Bull Put Spread', 'Bear Call Spread'];
            if (!supportedStrategies.includes(strategy)) return null;
            if (!this.rollAlertSettings.enabled) return null;

            const positions = group.positions || [];
            const underlying = group.underlying;
            const quote = this.underlyingQuotes[underlying];
            if (!quote || !quote.price) return null;
            const underlyingPrice = quote.price;

            const getStrike = (p) => {
                if (p.strike && p.strike > 0) return p.strike;
                const match = (p.symbol || '').match(/([CP])(\d+)/);
                if (match && match[2].length >= 3) return parseFloat(match[2].slice(0, -3) + '.' + match[2].slice(-3));
                return null;
            };
            const isShort = (p) => p.quantity_direction === 'Short' || (p.quantity || 0) < 0;
            const getOptionType = (p) => {
                if (p.option_type === 'Call') return 'C';
                if (p.option_type === 'Put') return 'P';
                const match = (p.symbol || '').match(/\d{6}([CP])/);
                return match ? match[1] : null;
            };

            const optionPositions = positions.filter(p => p.instrument_type && p.instrument_type.includes('OPTION'));
            if (optionPositions.length < 2) return null;

            let longLeg = null, shortLeg = null;
            for (const p of optionPositions) {
                if (isShort(p)) shortLeg = p;
                else longLeg = p;
            }
            if (!longLeg || !shortLeg) return null;

            const longStrike = getStrike(longLeg);
            const shortStrike = getStrike(shortLeg);
            if (!longStrike || !shortStrike) return null;

            const spreadWidth = Math.abs(shortStrike - longStrike);
            const numContracts = Math.abs(longLeg.quantity || 0);
            const totalCostBasis = Math.abs(positions.reduce((sum, p) => sum + (p.cost_basis || 0), 0));

            const isBullCall = strategy === 'Bull Call Spread';
            const isBullPut = strategy === 'Bull Put Spread';
            const isBearCall = strategy === 'Bear Call Spread';
            const isCredit = isBullPut || isBearCall;

            let maxProfit, maxLoss;
            if (isCredit) {
                maxProfit = totalCostBasis;
                maxLoss = (spreadWidth * 100 * numContracts) - totalCostBasis;
            } else {
                maxProfit = (spreadWidth * 100 * numContracts) - totalCostBasis;
                maxLoss = totalCostBasis;
            }

            if (maxProfit <= 0 || maxLoss <= 0) return null;

            const currentPnL = this.getGroupOpenPnL(group);
            const pctMaxProfit = ((currentPnL / maxProfit) * 100).toFixed(1);
            const pctMaxLoss = currentPnL < 0 ? ((Math.abs(currentPnL) / maxLoss) * 100).toFixed(1) : '0.0';

            const rewardRemaining = maxProfit - currentPnL;
            const riskRemaining = maxLoss + currentPnL;
            const rewardToRiskRaw = riskRemaining > 0 ? rewardRemaining / riskRemaining : 99;
            const rewardToRisk = rewardToRiskRaw >= 10 ? '10+' : rewardToRiskRaw.toFixed(2);

            const dte = this.getMinDTE(group) || 0;

            // Delta saturation
            let deltaSaturation = '0.0';
            const iv = this._getEffectiveIV(underlying);
            if (iv > 0 && dte > 0) {
                const T = dte / 365;
                const shortDelta = Math.abs(this._bsDelta(underlyingPrice, shortStrike, T, 0.04, iv, getOptionType(shortLeg) === 'C'));
                deltaSaturation = (shortDelta * 100).toFixed(1);
            }

            // Proximity to short strike
            const proximityToShort = ((Math.abs(underlyingPrice - shortStrike) / underlyingPrice) * 100).toFixed(1);

            // Badges
            const badges = [];
            const targets = this.strategyTargets[strategy] || {};
            const profitTarget = targets.profit_target_pct || 50;
            const lossLimit = targets.loss_target_pct || 100;

            if (this.rollAlertSettings.profitTarget && parseFloat(pctMaxProfit) >= profitTarget) {
                badges.push({ label: 'Profit Target', color: 'green' });
            }
            if (this.rollAlertSettings.lossLimit) {
                // Credit spreads: loss as % of credit received (|pctMaxProfit|)
                // Debit spreads: loss as % of debit paid (pctMaxLoss)
                const lossMetric = isCredit ? Math.abs(parseFloat(pctMaxProfit)) : parseFloat(pctMaxLoss);
                if (currentPnL < 0 && lossMetric >= lossLimit) {
                    badges.push({ label: 'Loss Limit', color: 'red' });
                }
            }
            if (this.rollAlertSettings.lateStage && dte <= 21 && dte > 0) {
                badges.push({ label: `${dte}d Left`, color: 'yellow' });
            }
            if (this.rollAlertSettings.lowRewardToRisk && rewardToRiskRaw < (isCredit ? 0.3 : 0.6)) {
                badges.push({ label: `R:R ${rewardToRisk}`, color: 'orange' });
            }

            let convexity;
            if (isCredit) {
                const lossRatio = parseFloat(pctMaxLoss);
                if (lossRatio < 50) convexity = 'Low Risk';
                else if (lossRatio < 100) convexity = 'Elevated Risk';
                else convexity = 'High Risk';
            } else {
                if (rewardToRiskRaw > 2) convexity = 'High';
                else if (rewardToRiskRaw > 0.8) convexity = 'Diminishing';
                else convexity = 'Low';
            }

            let borderColor = 'blue';
            if (badges.some(b => b.color === 'red')) borderColor = 'red';
            else if (badges.some(b => b.color === 'yellow' || b.color === 'orange')) borderColor = 'yellow';
            else if (badges.some(b => b.color === 'green')) borderColor = 'green';

            // Net position Greeks
            const longGreeks = this._getLegGreeks(longLeg, underlyingPrice, getStrike, getOptionType);
            const shortGreeks = this._getLegGreeks(shortLeg, underlyingPrice, getStrike, getOptionType);
            const longQty = Math.abs(longLeg.quantity || 0);
            const shortQty = Math.abs(shortLeg.quantity || 0);

            const netDelta = ((longGreeks.delta * longQty) + (shortGreeks.delta * -shortQty)) * 100;
            const netGamma = ((longGreeks.gamma * longQty) + (shortGreeks.gamma * -shortQty)) * 100;
            const netTheta = ((longGreeks.theta * longQty) + (shortGreeks.theta * -shortQty)) * 100;
            const netVega  = ((longGreeks.vega  * longQty) + (shortGreeks.vega  * -shortQty)) * 100;
            const greeksSource = (longGreeks.source === 'broker' || shortGreeks.source === 'broker') ? 'broker' : (longGreeks.source === 'bs' || shortGreeks.source === 'bs') ? 'bs' : 'none';

            let suggestion = null;
            let urgency = 'low';
            if (parseFloat(pctMaxProfit) >= profitTarget) {
                suggestion = `Consider closing: ${pctMaxProfit}% of max profit captured.`;
                urgency = 'medium';
            }
            const suggestionLossMetric = isCredit ? Math.abs(parseFloat(pctMaxProfit)) : parseFloat(pctMaxLoss);
            if (currentPnL < 0 && suggestionLossMetric >= lossLimit) {
                const lossDesc = isCredit ? 'of credit received' : 'of debit paid';
                suggestion = `Loss limit hit: ${suggestionLossMetric.toFixed(1)}% ${lossDesc}. Consider closing or rolling.`;
                urgency = 'high';
            }

            return {
                pctMaxProfit, pctMaxLoss, rewardToRisk, rewardToRiskRaw,
                deltaSaturation, proximityToShort, convexity, isCredit,
                maxProfit: formatNumber(maxProfit, 0),
                maxLoss: formatNumber(maxLoss, 0),
                netDelta, netGamma, netTheta, netVega, greeksSource,
                badges, borderColor, suggestion, urgency
            };
        },

        _bsDelta(S, K, T, r, sigma, isCall) {
            if (T <= 0 || sigma <= 0) return isCall ? (S > K ? 1 : 0) : (S < K ? -1 : 0);
            const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
            return isCall ? this._normalCDF(d1) : this._normalCDF(d1) - 1;
        },
        _normalPDF(x) {
            return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI);
        },
        _bsGreeks(S, K, T, r, sigma, isCall) {
            if (T <= 0.0001 || sigma <= 0 || S <= 0 || K <= 0) {
                return { delta: 0, gamma: 0, theta: 0, vega: 0 };
            }
            const sqrtT = Math.sqrt(T);
            const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * sqrtT);
            const d2 = d1 - sigma * sqrtT;
            const nd1 = this._normalCDF(d1);
            const phid1 = this._normalPDF(d1);
            const Kert = K * Math.exp(-r * T);

            const delta = isCall ? nd1 : nd1 - 1;
            const gamma = phid1 / (S * sigma * sqrtT);
            const theta = isCall
                ? (-(S * phid1 * sigma) / (2 * sqrtT) - r * Kert * this._normalCDF(d2)) / 365
                : (-(S * phid1 * sigma) / (2 * sqrtT) + r * Kert * this._normalCDF(-d2)) / 365;
            const vega = S * phid1 * sqrtT / 100;

            return { delta, gamma, theta, vega };
        },
        _getLegGreeks(leg, underlyingPrice, getStrike, getOptionType) {
            const optionQuote = this.underlyingQuotes[leg.symbol];

            // Prefer broker Greeks from DXFeed streaming
            if (optionQuote && optionQuote.delta != null) {
                return {
                    delta: optionQuote.delta,
                    gamma: optionQuote.gamma || 0,
                    theta: optionQuote.theta || 0,
                    vega: optionQuote.vega || 0,
                    source: 'broker',
                };
            }

            // Fallback: Black-Scholes
            const strike = getStrike(leg);
            const isCall = getOptionType(leg) === 'C';
            const dte = this.getMinDTE({ positions: [leg] }) || 0;
            if (!strike || dte <= 0) return { delta: 0, gamma: 0, theta: 0, vega: 0, source: 'none' };

            const T = Math.max(dte, 0.5) / 365;
            const iv = this._getEffectiveIV(leg.underlying || '');
            const greeks = this._bsGreeks(underlyingPrice, strike, T, 0.045, iv, isCall);
            return { ...greeks, source: 'bs' };
        },
        _normalCDF(x) {
            const t = 1 / (1 + 0.2316419 * Math.abs(x));
            const d = 0.3989422804014327;
            const p = d * Math.exp(-x * x / 2) * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
            return x > 0 ? 1 - p : p;
        },
        _getEffectiveIV(underlying) {
            const quote = this.underlyingQuotes[underlying];
            if (quote && quote.iv && quote.iv > 0) return quote.iv / 100;
            return 0.30;
        },

        // ===== Strategy Targets =====
        async loadStrategyTargets() {
            try {
                const response = await Auth.authFetch('/api/settings/targets');
                if (response.ok) {
                    const data = await response.json();
                    // API returns a list of {strategy_name, profit_target_pct, loss_target_pct}
                    const list = Array.isArray(data) ? data : (data.targets || []);
                    const mapped = {};
                    list.forEach(t => { if (t.strategy_name) mapped[t.strategy_name] = t; });
                    this.strategyTargets = mapped;
                }
            } catch (error) { console.error('Failed to load strategy targets:', error); }
        },
        loadRollAlertSettings() {
            try {
                const saved = localStorage.getItem('rollAlertSettings');
                if (saved) this.rollAlertSettings = { ...this.rollAlertSettings, ...JSON.parse(saved) };
            } catch (e) { /* use defaults */ }
        },

        // ===== Notes (DB-persisted) =====
        async loadComments() {
            try {
                const response = await Auth.authFetch('/api/position-notes');
                if (response.ok) {
                    const data = await response.json();
                    this.positionComments = data.notes || {};
                } else {
                    this.positionComments = {};
                }
            } catch (error) {
                console.error('Error loading position notes:', error);
                this.positionComments = {};
            }
            // One-time migration from localStorage
            try {
                const stored = localStorage.getItem('positionComments');
                if (stored) {
                    const local = JSON.parse(stored);
                    let migrated = false;
                    for (const [key, value] of Object.entries(local)) {
                        if (value && !this.positionComments[key]) {
                            this.positionComments[key] = value;
                            Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ note: value })
                            }).catch(err => console.error('Migration save error:', err));
                            migrated = true;
                        }
                    }
                    localStorage.removeItem('positionComments');
                    if (migrated) console.log('Migrated position notes from localStorage to DB');
                }
            } catch (e) { /* ignore migration errors */ }
        },
        _migrateCommentKeys() {
            // Migrate notes from old chain_{source_chain_id} keys to new group_{group_id} keys
            try {
                for (const item of this.allItems) {
                    if (item._isSubtotal) continue;
                    const groupId = item.group_id || item.chain_id;
                    const sourceChainId = item.source_chain_id;
                    if (!groupId || !sourceChainId || groupId === sourceChainId) continue;

                    const newKey = `group_${groupId}`;
                    const oldKey = `chain_${sourceChainId}`;

                    // If note exists under old key but not new key, migrate it
                    if (this.positionComments[oldKey] && !this.positionComments[newKey]) {
                        this.positionComments[newKey] = this.positionComments[oldKey];
                        Auth.authFetch(`/api/position-notes/${encodeURIComponent(newKey)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ note: this.positionComments[oldKey] })
                        }).catch(err => console.error('Comment key migration error:', err));
                    }

                    // Also check the old chain_{chain_id} key (chain_id === group_id now)
                    const oldChainKey = `chain_${groupId}`;
                    if (this.positionComments[oldChainKey] && !this.positionComments[newKey]) {
                        this.positionComments[newKey] = this.positionComments[oldChainKey];
                        Auth.authFetch(`/api/position-notes/${encodeURIComponent(newKey)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ note: this.positionComments[oldChainKey] })
                        }).catch(err => console.error('Comment key migration error:', err));
                    }
                }
            } catch (e) { /* ignore migration errors */ }
        },
        getCommentKey(group) {
            if (group._isSubtotal) return null;
            const groupId = group.group_id || group.chain_id || group.chainId;
            if (groupId) return `group_${groupId}`;
            return `pos_${group.underlying}_${group.accountNumber || 'default'}`;
        },
        getPositionComment(group) {
            const key = this.getCommentKey(group);
            if (!key) return '';
            return this.positionComments[key] || '';
        },
        updatePositionComment(group, value) {
            const key = this.getCommentKey(group);
            if (!key) return;
            this.positionComments[key] = value;
            if (this._noteSaveTimers[key]) {
                clearTimeout(this._noteSaveTimers[key]);
            }
            this._noteSaveTimers[key] = setTimeout(() => {
                Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note: value })
                }).catch(err => console.error('Error saving position note:', err));
                delete this._noteSaveTimers[key];
            }, 500);
        },

        // Get single-letter account symbol (R=Roth, I=Individual, T=Traditional)
        getAccountSymbol(accountNumber) {
            const account = this.accounts.find(a => a.account_number === accountNumber);
            if (!account) return '?';
            const name = (account.account_name || '').toUpperCase();
            if (name.includes('ROTH')) return 'R';
            if (name.includes('INDIVIDUAL')) return 'I';
            if (name.includes('TRADITIONAL')) return 'T';
            return name.charAt(0) || '?';
        }
    }));
});
