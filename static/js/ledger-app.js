document.addEventListener('alpine:init', () => {
    Alpine.data('ledgerApp', () => ({
        // State
        groups: [],
        accounts: [],
        filteredGroups: [],
        selectedAccount: '',
        filterUnderlying: '',
        timePeriod: 'all',
        showOpen: true,
        showClosed: true,
        viewMode: 'positions',
        sortColumn: 'opening_date',
        sortDirection: 'desc',
        loading: true,
        selectedLots: [],
        stats: { totalPnl: 0, openCount: 0, closedCount: 0 },
        filterDirection: [],
        filterType: [],
        groupNotes: {},
        orderComments: {},
        _noteSaveTimers: {},
        availableTags: [],
        tagPopoverGroup: null,
        tagSearch: '',
        tagHighlightIndex: -1,
        async init() {
            await Auth.requireAuth();
            await Auth.requireTastytrade();
            await this.loadAccounts();

            // Restore state from localStorage
            const saved = localStorage.getItem('ledger_state');
            if (saved) {
                try {
                    const state = JSON.parse(saved);
                    this.timePeriod = state.timePeriod || 'all';
                    this.showOpen = state.showOpen !== undefined ? state.showOpen : true;
                    this.showClosed = state.showClosed !== undefined ? state.showClosed : true;
                    this.sortColumn = state.sortColumn || 'opening_date';
                    this.sortDirection = state.sortDirection || 'desc';
                    this.viewMode = state.viewMode || 'positions';
                    this.filterDirection = state.filterDirection || [];
                    this.filterType = state.filterType || [];
                } catch (e) {}
            }

            // Sync account selection from other pages
            const savedAccount = localStorage.getItem('trade_journal_selected_account');
            if (savedAccount) {
                this.selectedAccount = savedAccount;
            }

            // URL params override saved state
            const urlParams = new URLSearchParams(window.location.search);
            const underlyingParam = urlParams.get('underlying');
            if (underlyingParam) {
                this.filterUnderlying = underlyingParam.toUpperCase();
                this.timePeriod = 'all';
                this.showOpen = true;
                this.showClosed = true;
            } else {
                // Sync symbol filter from other pages
                const savedUnderlying = localStorage.getItem('trade_journal_selected_underlying');
                if (savedUnderlying) {
                    this.filterUnderlying = savedUnderlying;
                }
            }

            await this.fetchLedger();
            this.loadNotes();
            await this.loadAvailableTags();
        },

        async loadAccounts() {
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
            } catch (error) {
                console.error('Error loading accounts:', error);
            }
        },

        async fetchLedger() {
            this.loading = true;
            try {
                const params = new URLSearchParams();
                if (this.selectedAccount) params.set('account_number', this.selectedAccount);
                // Server-side underlying filter is exact match; we'll do client-side for partial
                const url = '/api/ledger' + (params.toString() ? '?' + params.toString() : '');
                const response = await Auth.authFetch(url);
                const data = await response.json();

                // Add expanded state
                this.groups = data.map(g => ({ ...g, expanded: false, _viewMode: null }));
                this.applyFilters();
            } catch (error) {
                console.error('Error fetching ledger:', error);
            } finally {
                this.loading = false;
            }
        },

        sortGroups(column) {
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                if (column === 'opening_date' || column === 'closing_date' || column === 'total_pnl') {
                    this.sortDirection = 'desc';
                } else {
                    this.sortDirection = 'asc';
                }
            }
            this.applyFilters();
            this.saveState();
        },

        applyFilters() {
            let filtered = [...this.groups];

            // Underlying filter (client-side, exact match)
            if (this.filterUnderlying) {
                const sym = this.filterUnderlying.toUpperCase();
                filtered = filtered.filter(g => (g.underlying || '').toUpperCase() === sym);
            }

            // Direction/Type category filter
            filtered = filtered.filter(g => this.groupMatchesCategoryFilters(g));

            // Status filter
            if (!this.showOpen) filtered = filtered.filter(g => g.status !== 'OPEN');
            if (!this.showClosed) filtered = filtered.filter(g => g.status !== 'CLOSED');

            // Time period filter
            if (this.timePeriod !== 'all') {
                let cutoffStart, cutoffEnd;
                const today = new Date();
                today.setHours(0, 0, 0, 0);

                if (this.timePeriod === 'today') {
                    cutoffStart = today;
                    cutoffEnd = null;
                } else if (this.timePeriod === 'yesterday') {
                    cutoffStart = new Date(today);
                    cutoffStart.setDate(cutoffStart.getDate() - 1);
                    cutoffEnd = null;
                } else {
                    const days = parseInt(this.timePeriod);
                    if (!isNaN(days)) {
                        cutoffStart = new Date(today);
                        cutoffStart.setDate(cutoffStart.getDate() - days);
                    }
                    cutoffEnd = null;
                }

                if (cutoffStart) {
                    filtered = filtered.filter(g => {
                        const opened = g.opening_date ? new Date(g.opening_date) : null;
                        const closed = g.closing_date ? new Date(g.closing_date) : null;
                        const inRange = (d) => d && d >= cutoffStart && (!cutoffEnd || d < cutoffEnd);
                        return inRange(opened) || inRange(closed);
                    });
                }
            }

            // Sort
            filtered.sort((a, b) => {
                let va, vb;
                const col = this.sortColumn;
                if (col === 'opening_date' || col === 'closing_date') {
                    va = a[col] || '';
                    vb = b[col] || '';
                } else if (col === 'underlying') {
                    va = a.underlying || '';
                    vb = b.underlying || '';
                } else if (col === 'strategy_label') {
                    va = a.strategy_label || '';
                    vb = b.strategy_label || '';
                } else if (col === 'status') {
                    va = a.status || '';
                    vb = b.status || '';
                } else if (col === 'lot_count') {
                    va = a.lot_count || 0;
                    vb = b.lot_count || 0;
                } else if (col === 'total_pnl') {
                    va = a.realized_pnl || 0;
                    vb = b.realized_pnl || 0;
                } else {
                    va = a[col] || '';
                    vb = b[col] || '';
                }

                let cmp = 0;
                if (typeof va === 'number' && typeof vb === 'number') {
                    cmp = va - vb;
                } else {
                    cmp = String(va).localeCompare(String(vb));
                }
                return this.sortDirection === 'desc' ? -cmp : cmp;
            });

            this.filteredGroups = filtered;
            this.computeStats();
        },

        computeStats() {
            let totalPnl = 0, openCount = 0, closedCount = 0;
            for (const g of this.filteredGroups) {
                totalPnl += g.realized_pnl || 0;
                if (g.status === 'OPEN') openCount++;
                else closedCount++;
            }
            this.stats = { totalPnl, openCount, closedCount };
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
                const idx = this.filterType.indexOf(value);
                if (idx >= 0) {
                    this.filterType.splice(idx, 1);
                } else {
                    this.filterType = [value];
                }
            }
            this.saveState();
            this.applyFilters();
        },

        groupMatchesCategoryFilters(group) {
            const strategy = group.strategy_label || '';
            const noDirectionFilter = this.filterDirection.length === 0;
            const noTypeFilter = this.filterType.length === 0;
            if (noDirectionFilter && noTypeFilter) return true;
            const cat = STRATEGY_CATEGORIES[strategy];
            if (!cat) return noDirectionFilter && noTypeFilter;
            if (cat.isShares) return noDirectionFilter && noTypeFilter;
            const directionMatch = noDirectionFilter || this.filterDirection.includes(cat.direction);
            const typeMatch = noTypeFilter || this.filterType.includes(cat.type);
            return directionMatch && typeMatch;
        },

        cleanUrlParams() {
            const url = new URL(window.location);
            if (url.searchParams.has('underlying')) {
                url.searchParams.delete('underlying');
                window.history.replaceState({}, '', url.pathname + (url.search || ''));
            }
        },

        onAccountChange() {
            localStorage.setItem('trade_journal_selected_account', this.selectedAccount);
            this.fetchLedger();
        },

        saveState() {
            localStorage.setItem('ledger_state', JSON.stringify({
                timePeriod: this.timePeriod,
                showOpen: this.showOpen,
                showClosed: this.showClosed,
                sortColumn: this.sortColumn,
                sortDirection: this.sortDirection,
                viewMode: this.viewMode,
                filterDirection: this.filterDirection,
                filterType: this.filterType,
            }));
        },

        toggleGroupMoveMode(group) {
            const wasMoving = group._movingLots;
            this.clearAllMoveMode();
            if (!wasMoving) {
                group._movingLots = true;
                group.expanded = true;
            }
        },

        clearAllMoveMode() {
            for (const g of this.groups) {
                g._movingLots = false;
            }
            this.selectedLots = [];
        },

        cancelMoveMode() {
            this.clearAllMoveMode();
        },

        groupViewMode(group) {
            return group._viewMode || this.viewMode;
        },

        sortedLots(group) {
            return (group.lots || []).slice().sort((a, b) => {
                // Open lots first, then closed
                const aOpen = a.status !== 'CLOSED' ? 0 : 1;
                const bOpen = b.status !== 'CLOSED' ? 0 : 1;
                if (aOpen !== bOpen) return aOpen - bOpen;
                // Within same status: entry date desc (most recent first)
                const aDate = a.entry_date || '';
                const bDate = b.entry_date || '';
                if (aDate !== bDate) return bDate.localeCompare(aDate);
                // Tie-break: expiration desc, then strike desc
                const aExp = a.expiration || '';
                const bExp = b.expiration || '';
                if (aExp !== bExp) return bExp.localeCompare(aExp);
                return (b.strike || 0) - (a.strike || 0);
            });
        },

        sortedOptionLots(group) {
            // Option lots + closed equity lots — rendered individually
            return this.sortedLots(group).filter(l => l.instrument_type !== 'EQUITY' || l.status === 'CLOSED');
        },

        openEquityLots(group) {
            return (group.lots || []).filter(l => l.instrument_type === 'EQUITY' && l.status !== 'CLOSED')
                .sort((a, b) => (b.entry_date || '').localeCompare(a.entry_date || ''));
        },

        equityAggregate(group) {
            const lots = this.openEquityLots(group);
            if (lots.length === 0) return null;
            const totalQty = lots.reduce((s, l) => s + (l.remaining_quantity ?? l.quantity), 0);
            const totalCost = lots.reduce((s, l) => s + (l.cost_basis || 0), 0);
            return {
                quantity: totalQty,
                avgPrice: totalQty !== 0 ? Math.abs(totalCost) / Math.abs(totalQty) : 0,
                costBasis: totalCost,
                lotCount: lots.length,
            };
        },

        toggleAllEquityLots(group) {
            const ids = this.openEquityLots(group).map(l => l.transaction_id);
            const allSelected = ids.every(id => this.selectedLots.includes(id));
            if (allSelected) {
                this.selectedLots = this.selectedLots.filter(id => !ids.includes(id));
            } else {
                for (const id of ids) {
                    if (!this.selectedLots.includes(id)) this.selectedLots.push(id);
                }
            }
        },

        toggleLotSelection(transactionId) {
            const idx = this.selectedLots.indexOf(transactionId);
            if (idx >= 0) {
                this.selectedLots.splice(idx, 1);
            } else {
                this.selectedLots.push(transactionId);
            }
        },

        toggleLotExpand(lot) {
            lot._expanded = !lot._expanded;
        },

        _getSourceInfo() {
            // Find the underlying + account + source group IDs from selected lots
            let underlying = null, account = null;
            const sourceIds = new Set();
            for (const g of this.groups) {
                for (const lot of (g.lots || [])) {
                    if (this.selectedLots.includes(lot.transaction_id)) {
                        underlying = g.underlying;
                        account = g.account_number;
                        sourceIds.add(g.group_id);
                        break;
                    }
                }
            }
            return { underlying, account, sourceIds };
        },

        _inferStrategyLabel() {
            const lots = [];
            for (const g of this.groups) {
                for (const lot of (g.lots || [])) {
                    if (this.selectedLots.includes(lot.transaction_id)) {
                        lots.push(lot);
                    }
                }
            }
            const optionLots = lots.filter(l => l.option_type);
            if (optionLots.length === 0) return null;
            const firstType = optionLots[0].option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put';
            const firstDir = optionLots[0].quantity < 0 ? 'Short' : 'Long';
            const allSame = optionLots.every(l => {
                const t = l.option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put';
                const d = l.quantity < 0 ? 'Short' : 'Long';
                return t === firstType && d === firstDir;
            });
            return allSame ? `${firstDir} ${firstType}` : null;
        },

        isEligibleTarget(group) {
            if (this.selectedLots.length === 0) return false;
            const { underlying, account, sourceIds } = this._getSourceInfo();
            return group.underlying === underlying &&
                   group.account_number === account &&
                   !sourceIds.has(group.group_id);
        },

        isSourceGroup(group) {
            if (this.selectedLots.length === 0) return false;
            const { sourceIds } = this._getSourceInfo();
            return sourceIds.has(group.group_id);
        },

        async moveLots(targetGroupId) {
            if (!targetGroupId || this.selectedLots.length === 0) return;

            // Create new group if requested
            if (targetGroupId === '__new__') {
                const { underlying, account } = this._getSourceInfo();
                const strategyLabel = this._inferStrategyLabel();
                try {
                    const resp = await Auth.authFetch('/api/ledger/groups', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ account_number: account, underlying: underlying, strategy_label: strategyLabel })
                    });
                    const result = await resp.json();
                    targetGroupId = result.group_id;
                } catch (error) {
                    console.error('Error creating group:', error);
                    return;
                }
            }

            try {
                await Auth.authFetch('/api/ledger/move-lots', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        transaction_ids: this.selectedLots,
                        target_group_id: targetGroupId
                    })
                });
                this.clearAllMoveMode();
                await this.fetchLedger();
            } catch (error) {
                console.error('Error moving lots:', error);
            }
        },

        async updateGroupStrategy(group, value) {
            if (value === group.strategy_label) return;
            try {
                await Auth.authFetch(`/api/ledger/groups/${group.group_id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ strategy_label: value })
                });
                group.strategy_label = value;
            } catch (error) {
                console.error('Error updating strategy:', error);
            }
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

        getAccountBadgeClass(accountNumber) {
            const symbol = this.getAccountSymbol(accountNumber);
            if (symbol === 'R') return 'bg-purple-900/60 text-purple-400';
            if (symbol === 'I') return 'bg-blue-900/60 text-blue-400';
            if (symbol === 'T') return 'bg-green-900/60 text-green-400';
            return 'bg-tv-border text-tv-muted';
        },

        formatAction(action) {
            if (!action) return '';
            const cleanAction = action.replace(/^(ORDERACTION\.|OrderAction\.)/, '');
            const actionMap = {
                'SELL_TO_OPEN': 'STO', 'BUY_TO_CLOSE': 'BTC',
                'BUY_TO_OPEN': 'BTO', 'SELL_TO_CLOSE': 'STC',
                'EXPIRED': 'EXPIRED', 'ASSIGNED': 'ASSIGNED',
                'EXERCISED': 'EXERCISED', 'CASH_SETTLED': 'CASH_SETTLED'
            };
            return actionMap[cleanAction] || cleanAction;
        },

        getDisplayQuantity(position) {
            if (!position || typeof position.quantity === 'undefined') return 0;
            const currentAction = (position.closing_action || position.opening_action || '').toUpperCase();
            const isSellAction = currentAction.includes('SELL') || currentAction.includes('STC') || currentAction.includes('STO');
            return isSellAction ? -Math.abs(position.quantity) : Math.abs(position.quantity);
        },

        // ========== Credit/Debit Helpers (for Action view) ==========

        getCreditDebitDivisor(order) {
            if (!order || !order.positions || order.positions.length === 0) return 0;
            const normalizeAction = (action) => {
                if (!action) return '';
                return action.replace('OrderAction.', '').toUpperCase();
            };
            const closingPositions = order.positions.filter(pos =>
                pos.closing_action && (pos.closing_action === 'BTC' || pos.closing_action === 'STC')
            );
            if (closingPositions.length > 0) {
                const qty = Math.abs(closingPositions[0].quantity || 0);
                if (qty > 0) return qty;
            }
            const closingByAction = order.positions.filter(pos => {
                const n = normalizeAction(pos.opening_action);
                return (n === 'BTC' || n === 'BUY_TO_CLOSE' || n === 'STC' || n === 'SELL_TO_CLOSE') && pos.status === 'CLOSED';
            });
            if (closingByAction.length > 0) {
                const qty = Math.abs(closingByAction[0].quantity || 0);
                if (qty > 0) return qty;
            }
            const openingPositions = order.positions.filter(pos => {
                const n = normalizeAction(pos.opening_action);
                return (n === 'BTO' || n === 'BUY_TO_OPEN' || n === 'STO' || n === 'SELL_TO_OPEN') && pos.status !== 'CLOSED';
            });
            if (openingPositions.length > 0) {
                const qty = Math.abs(openingPositions[0].quantity || 0);
                if (qty > 0) return qty;
            }
            return Math.abs(order.positions[0].quantity || 0);
        },

        calculateRollCreditDebit(order) {
            if (!order || order.order_type !== 'ROLLING' || !order.positions || order.positions.length === 0) return null;
            const normalizeAction = (action) => action ? action.replace('OrderAction.', '').toUpperCase() : '';
            const openingPositions = order.positions.filter(pos => {
                const a = normalizeAction(pos.opening_action);
                return a === 'BTO' || a === 'BUY_TO_OPEN' || a === 'STO' || a === 'SELL_TO_OPEN';
            });
            const divisor = openingPositions.length > 0
                ? Math.abs(openingPositions[0].quantity || 0)
                : this.getCreditDebitDivisor(order);
            if (divisor === 0) return null;
            const perRatioAmount = Math.abs(order.total_pnl || 0) / divisor / 100;
            return { amount: perRatioAmount, type: (order.total_pnl || 0) > 0 ? 'credit' : 'debit' };
        },

        formatRollCreditDebit(order) {
            const d = this.calculateRollCreditDebit(order);
            return d ? `${d.amount.toFixed(2)} ${d.type}` : '';
        },

        calculateOpeningCreditDebit(order) {
            if (!order || order.order_type !== 'OPENING' || !order.positions || order.positions.length === 0) return null;
            const divisor = this.getCreditDebitDivisor(order);
            if (divisor === 0) return null;
            const perRatioAmount = Math.abs(order.total_pnl || 0) / divisor / 100;
            return { amount: perRatioAmount, type: (order.total_pnl || 0) > 0 ? 'credit' : 'debit' };
        },

        formatOpeningCreditDebit(order) {
            const d = this.calculateOpeningCreditDebit(order);
            return d ? `${d.amount.toFixed(2)} ${d.type}` : '';
        },

        calculateClosingCreditDebit(order) {
            if (!order || order.order_type !== 'CLOSING' || !order.positions || order.positions.length === 0) return null;
            const divisor = this.getCreditDebitDivisor(order);
            if (divisor === 0) return null;
            const perRatioAmount = Math.abs(order.total_pnl || 0) / divisor / 100;
            return { amount: perRatioAmount, type: (order.total_pnl || 0) > 0 ? 'credit' : 'debit' };
        },

        formatClosingCreditDebit(order) {
            const d = this.calculateClosingCreditDebit(order);
            return d ? `${d.amount.toFixed(2)} ${d.type}` : '';
        },

        // ========== Notes (DB-persisted) ==========

        async loadNotes() {
            try {
                const [notesResp, commentsResp] = await Promise.all([
                    Auth.authFetch('/api/position-notes'),
                    Auth.authFetch('/api/order-comments'),
                ]);
                if (notesResp.ok) {
                    const data = await notesResp.json();
                    this.groupNotes = data.notes || {};
                }
                if (commentsResp.ok) {
                    const data = await commentsResp.json();
                    this.orderComments = data.comments || {};
                }
            } catch (error) {
                console.error('Error loading notes:', error);
            }
        },

        getGroupNote(group) {
            return this.groupNotes['group_' + group.group_id] || '';
        },

        updateGroupNote(group, value) {
            const key = 'group_' + group.group_id;
            this.groupNotes[key] = value;
            if (this._noteSaveTimers[key]) {
                clearTimeout(this._noteSaveTimers[key]);
            }
            this._noteSaveTimers[key] = setTimeout(() => {
                Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ note: value })
                }).catch(err => console.error('Error saving group note:', err));
                delete this._noteSaveTimers[key];
            }, 500);
        },

        getOrderComment(orderId) {
            return this.orderComments[orderId] || '';
        },

        updateOrderComment(orderId, value) {
            this.orderComments[orderId] = value;
            if (this._noteSaveTimers['order_' + orderId]) {
                clearTimeout(this._noteSaveTimers['order_' + orderId]);
            }
            this._noteSaveTimers['order_' + orderId] = setTimeout(() => {
                Auth.authFetch(`/api/order-comments/${encodeURIComponent(orderId)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ comment: value })
                }).catch(err => console.error('Error saving order comment:', err));
                delete this._noteSaveTimers['order_' + orderId];
            }, 500);
        },

        // ========== Tag Methods ==========

        async loadAvailableTags() {
            try {
                const resp = await Auth.authFetch('/api/tags');
                this.availableTags = await resp.json();
            } catch (e) { console.error('Error loading tags:', e); }
        },

        get filteredTagSuggestions() {
            const search = (this.tagSearch || '').toLowerCase();
            const group = this.groups.find(g => g.group_id === this.tagPopoverGroup);
            const appliedIds = (group?.tags || []).map(t => t.id);
            return this.availableTags
                .filter(t => !appliedIds.includes(t.id))
                .filter(t => !search || t.name.toLowerCase().includes(search));
        },

        openTagPopover(groupId, event) {
            if (event) event.stopPropagation();
            this.tagPopoverGroup = this.tagPopoverGroup === groupId ? null : groupId;
            this.tagSearch = '';
            this.tagHighlightIndex = -1;
            if (this.tagPopoverGroup) {
                this.$nextTick(() => {
                    const input = document.getElementById('ledger-tag-input-' + groupId);
                    if (input) input.focus();
                });
            }
        },

        closeTagPopover() {
            this.tagPopoverGroup = null;
            this.tagSearch = '';
            this.tagHighlightIndex = -1;
        },

        async addTagToGroup(group, nameOrTag) {
            const payload = typeof nameOrTag === 'string'
                ? { name: nameOrTag.trim() }
                : { tag_id: nameOrTag.id };
            if (payload.name === '' && !payload.tag_id) return;
            try {
                const resp = await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const tag = await resp.json();
                if (!group.tags) group.tags = [];
                if (!group.tags.find(t => t.id === tag.id)) {
                    group.tags.push(tag);
                }
                await this.loadAvailableTags();
                this.tagSearch = '';
            } catch (e) { console.error('Error adding tag:', e); }
        },

        async removeTagFromGroup(group, tagId, event) {
            if (event) event.stopPropagation();
            try {
                await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags/${tagId}`, {
                    method: 'DELETE',
                });
                group.tags = (group.tags || []).filter(t => t.id !== tagId);
            } catch (e) { console.error('Error removing tag:', e); }
        },

        async handleTagInput(event, group) {
            const suggestions = this.filteredTagSuggestions;
            const hasCreateOption = this.tagSearch.trim() && !suggestions.find(t => t.name.toLowerCase() === this.tagSearch.trim().toLowerCase());
            const totalItems = suggestions.length + (hasCreateOption ? 1 : 0);

            if (event.key === 'ArrowDown') {
                event.preventDefault();
                this.tagHighlightIndex = this.tagHighlightIndex < totalItems - 1 ? this.tagHighlightIndex + 1 : 0;
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                this.tagHighlightIndex = this.tagHighlightIndex > 0 ? this.tagHighlightIndex - 1 : totalItems - 1;
            } else if (event.key === 'Enter') {
                event.preventDefault();
                if (this.tagHighlightIndex >= 0 && this.tagHighlightIndex < suggestions.length) {
                    await this.addTagToGroup(group, suggestions[this.tagHighlightIndex]);
                    this.closeTagPopover();
                } else if (this.tagHighlightIndex === suggestions.length && hasCreateOption) {
                    await this.addTagToGroup(group, this.tagSearch.trim());
                    this.closeTagPopover();
                } else {
                    const search = this.tagSearch.trim();
                    if (!search) return;
                    const exactMatch = suggestions.find(t => t.name.toLowerCase() === search.toLowerCase());
                    await this.addTagToGroup(group, exactMatch || search);
                    this.closeTagPopover();
                }
            } else if (event.key === 'Escape') {
                this.closeTagPopover();
            } else {
                this.tagHighlightIndex = -1;
            }
        },
    }));
});
