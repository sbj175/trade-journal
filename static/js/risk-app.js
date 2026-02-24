document.addEventListener('alpine:init', () => {
    Alpine.data('riskApp', () => ({
        // ==================== STATE ====================
        rawPositions: {},
        accountBalances: {},
        quotes: {},
        accounts: [],
        selectedAccount: '',
        isLoading: true,
        error: null,
        ws: null,
        liveQuotesActive: false,
        greeksSource: 'Black-Scholes',
        _chartTimer: null,
        _charts: {},
        sortColumn: 'deltaDollars',
        sortDirection: 'desc',

        // ==================== LIFECYCLE ====================
        async init() {
            await Auth.requireAuth();
            await this.fetchData();
            // Restore saved account selection AFTER accounts are loaded
            this.selectedAccount = localStorage.getItem('trade_journal_selected_account') || '';
            this.connectWebSocket();
        },

        async fetchData() {
            this.isLoading = true;
            try {
                const [posRes, balRes, acctRes] = await Promise.all([
                    Auth.authFetch('/api/positions'),
                    Auth.authFetch('/api/account-balances'),
                    Auth.authFetch('/api/accounts')
                ]);
                if (posRes.ok) this.rawPositions = await posRes.json();
                if (balRes.ok) {
                    const balData = await balRes.json();
                    const balances = balData.balances || balData;
                    this.accountBalances = {};
                    if (Array.isArray(balances)) {
                        balances.forEach(b => { this.accountBalances[b.account_number] = b; });
                    }
                }
                if (acctRes.ok) {
                    const acctData = await acctRes.json();
                    this.accounts = acctData.accounts || acctData || [];
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
                }
            } catch (e) {
                this.error = e.message;
                console.error('Failed to fetch data:', e);
            }
            this.isLoading = false;
            this.$nextTick(() => {
                if (this.allPositions.length > 0) this.renderAllCharts();
            });
        },

        // ==================== WEBSOCKET ====================
        async connectWebSocket() {
            const wsUrl = await Auth.getAuthenticatedWsUrl('/ws/quotes');
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                setTimeout(() => this.subscribeToQuotes(), 500);
            };

            this.ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'quotes' && msg.data) {
                        // Replace entire object to trigger Alpine reactivity
                        this.quotes = { ...this.quotes, ...msg.data };
                        this.liveQuotesActive = true;
                        const hasStreamGreeks = Object.values(msg.data).some(q => q.delta != null);
                        if (hasStreamGreeks) this.greeksSource = 'DXFeed + Black-Scholes';
                        this.debouncedUpdateCharts();
                    }
                } catch (e) { /* ignore parse errors */ }
            };

            this.ws.onclose = () => {
                this.liveQuotesActive = false;
                setTimeout(() => this.connectWebSocket(), 5000);
            };

            this.ws.onerror = () => { /* handled by onclose */ };
        },

        subscribeToQuotes() {
            const symbols = [...new Set(this.allPositions.map(p => this.getUnderlying(p)).filter(Boolean))];
            if (symbols.length > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ subscribe: symbols }));
            }
        },

        debouncedUpdateCharts() {
            if (this._chartTimer) return;
            this._chartTimer = setTimeout(() => {
                this._chartTimer = null;
                this.renderAllCharts();
            }, 2000);
        },

        // ==================== COMPUTED PROPERTIES ====================
        get allPositions() {
            let all = [];
            const sources = this.selectedAccount
                ? { [this.selectedAccount]: this.rawPositions[this.selectedAccount] || [] }
                : this.rawPositions;
            for (const [acct, positions] of Object.entries(sources)) {
                if (Array.isArray(positions)) all.push(...positions);
            }
            return all;
        },

        get enrichedPositions() {
            return this.allPositions.map(p => this.enrichPosition(p)).filter(Boolean);
        },

        get underlyingGroups() {
            const groups = {};
            this.enrichedPositions.forEach(pos => {
                const u = pos._underlying;
                if (!groups[u]) {
                    groups[u] = {
                        underlying: u, positions: [],
                        netDelta: 0, netGamma: 0, netTheta: 0, netVega: 0,
                        deltaDollars: 0, maxRisk: 0, unrealizedPnl: 0,
                        underlyingPrice: 0, positionCount: 0
                    };
                }
                const g = groups[u];
                g.positions.push(pos);
                g.netDelta += pos._posDelta;
                g.netGamma += pos._posGamma;
                g.netTheta += pos._posTheta;
                g.netVega += pos._posVega;
                g.deltaDollars += pos._deltaDollars;
                g.unrealizedPnl += pos._unrealizedPnl;
                g.underlyingPrice = pos._underlyingPrice;
                g.positionCount++;
            });
            // Calculate spread-aware max risk per underlying
            for (const g of Object.values(groups)) {
                g.maxRisk = this.calcCapitalAtRisk(g.positions);
            }
            return Object.values(groups);
        },

        get sortedGroups() {
            const groups = [...this.underlyingGroups];
            const col = this.sortColumn;
            const dir = this.sortDirection === 'asc' ? 1 : -1;
            groups.sort((a, b) => {
                let va = a[col], vb = b[col];
                if (col === 'underlying') return dir * String(va).localeCompare(String(vb));
                // Sort by absolute value for financial metrics
                if (col === 'deltaDollars' || col === 'netDelta' || col === 'netTheta' || col === 'netVega') {
                    return dir * (Math.abs(va) - Math.abs(vb));
                }
                return dir * ((va || 0) - (vb || 0));
            });
            return groups;
        },

        get portfolioTotals() {
            const groups = this.underlyingGroups;
            return {
                netDelta: groups.reduce((s, g) => s + g.netDelta, 0),
                netGamma: groups.reduce((s, g) => s + g.netGamma, 0),
                netTheta: groups.reduce((s, g) => s + g.netTheta, 0),
                netVega: groups.reduce((s, g) => s + g.netVega, 0),
                deltaDollars: groups.reduce((s, g) => s + g.deltaDollars, 0),
                totalMaxRisk: groups.reduce((s, g) => s + g.maxRisk, 0),
                totalPnl: groups.reduce((s, g) => s + g.unrealizedPnl, 0),
                positionCount: this.enrichedPositions.length,
                underlyingCount: groups.length,
            };
        },

        get currentBalance() {
            if (!this.selectedAccount || this.selectedAccount === '') {
                const vals = Object.values(this.accountBalances);
                if (vals.length === 0) return null;
                return vals.reduce((acc, b) => ({
                    cash_balance: (acc.cash_balance || 0) + (b.cash_balance || 0),
                    derivative_buying_power: (acc.derivative_buying_power || 0) + (b.derivative_buying_power || 0),
                    equity_buying_power: (acc.equity_buying_power || 0) + (b.equity_buying_power || 0),
                    net_liquidating_value: (acc.net_liquidating_value || 0) + (b.net_liquidating_value || 0),
                }), {});
            }
            return this.accountBalances[this.selectedAccount] || null;
        },

        get bpUtilization() {
            const bal = this.currentBalance;
            if (!bal || !bal.net_liquidating_value) return 0;
            const nlv = bal.net_liquidating_value;
            const dbp = bal.derivative_buying_power || 0;
            if (nlv <= 0) return 0;
            return Math.max(0, Math.min(100, ((nlv - dbp) / nlv) * 100));
        },

        // ==================== OCC SYMBOL PARSER ====================
        // Parses OCC option symbols like "LQDA  260320C00060000"
        // Format: SYMBOL(padded to 6) YYMMDD C/P SSSSSSSS (strike * 1000)
        parseOCCSymbol(symbol) {
            if (!symbol || symbol.length < 15) return null;
            // Find the date+type+strike portion: 6 digits + C/P + 8 digits at the end
            const match = symbol.match(/(\d{6})([CP])(\d{8})\s*$/);
            if (!match) return null;
            const dateStr = match[1]; // YYMMDD
            const optionType = match[2]; // C or P
            const strikeRaw = parseInt(match[3], 10); // strike * 1000
            const strike = strikeRaw / 1000;
            const year = 2000 + parseInt(dateStr.substring(0, 2), 10);
            const month = parseInt(dateStr.substring(2, 4), 10) - 1;
            const day = parseInt(dateStr.substring(4, 6), 10);
            const expiration = new Date(year, month, day);
            return { optionType, strike, expiration };
        },

        // ==================== POSITION ENRICHMENT ====================
        enrichPosition(pos) {
            const underlying = this.getUnderlying(pos);
            if (!underlying) return null;
            const quote = this.quotes[underlying] || {};
            const underlyingPrice = quote.price || quote.mark || quote.last || 0;
            if (underlyingPrice <= 0) {
                return this._basicPosition(pos, underlying, 0);
            }

            const isOpt = this.isOptionPosition(pos);
            const signedQty = this.getSignedQty(pos);

            if (isOpt) {
                // Parse strike/type from OCC symbol if DB fields are null
                const occ = this.parseOCCSymbol(pos.symbol);
                const strike = pos.strike_price || (occ ? occ.strike : 0);
                const optType = this.getOptionType(pos, occ);
                const dte = this.getDTE(pos, occ);
                if (strike <= 0 || dte <= 0) {
                    return this._basicPosition(pos, underlying, underlyingPrice);
                }
                const T = Math.max(dte, 0.5) / 365;
                const iv = this._getIV(pos, quote);
                const r = 0.045;

                const greeks = this.bsGreeks(underlyingPrice, strike, T, r, iv, optType);

                return {
                    ...pos,
                    _underlying: underlying,
                    _underlyingPrice: underlyingPrice,
                    _isOption: true,
                    _signedQty: signedQty,
                    _strike: strike,
                    _optionType: optType,
                    _dte: dte,
                    _iv: iv * 100,
                    _posDelta: greeks.delta * signedQty * 100,
                    _posGamma: greeks.gamma * signedQty * 100,
                    _posTheta: greeks.theta * signedQty * 100,
                    _posVega: greeks.vega * signedQty * 100,
                    _deltaDollars: greeks.delta * signedQty * 100 * underlyingPrice,
                    _notional: Math.abs(signedQty) * 100 * underlyingPrice,
                    _unrealizedPnl: parseFloat(pos.unrealized_pnl) || 0,
                };
            } else {
                return {
                    ...pos,
                    _underlying: underlying,
                    _underlyingPrice: underlyingPrice,
                    _isOption: false,
                    _signedQty: signedQty,
                    _strike: 0,
                    _optionType: '',
                    _dte: 0,
                    _iv: 0,
                    _posDelta: signedQty,
                    _posGamma: 0,
                    _posTheta: 0,
                    _posVega: 0,
                    _deltaDollars: signedQty * underlyingPrice,
                    _notional: Math.abs(signedQty) * underlyingPrice,
                    _unrealizedPnl: parseFloat(pos.unrealized_pnl) || 0,
                };
            }
        },

        _basicPosition(pos, underlying, price) {
            const isOpt = this.isOptionPosition(pos);
            const signedQty = this.getSignedQty(pos);
            return {
                ...pos,
                _underlying: underlying,
                _underlyingPrice: price,
                _isOption: isOpt,
                _signedQty: signedQty,
                _strike: 0,
                _optionType: '',
                _dte: 0,
                _iv: 0,
                // Equity positions still contribute delta even without quotes for Greeks
                _posDelta: isOpt ? 0 : signedQty,
                _posGamma: 0, _posTheta: 0, _posVega: 0,
                _deltaDollars: isOpt ? 0 : signedQty * price,
                _notional: isOpt ? 0 : Math.abs(signedQty) * price,
                _unrealizedPnl: parseFloat(pos.unrealized_pnl) || 0,
            };
        },

        _getIV(pos, quote) {
            if (quote.iv && quote.iv > 0) return quote.iv / 100;
            return 0.30; // 30% default
        },

        getUnderlying(pos) {
            return pos.underlying_symbol || pos.underlying || '';
        },

        isOptionPosition(pos) {
            const t = (pos.instrument_type || '').toLowerCase();
            return t.includes('option');
        },

        getOptionType(pos, occ) {
            // Try database field first
            const ot = (pos.option_type || '').toUpperCase();
            if (ot === 'C' || ot === 'CALL') return 'C';
            if (ot === 'P' || ot === 'PUT') return 'P';
            // Fall back to OCC symbol parse
            if (occ && occ.optionType) return occ.optionType;
            // Last resort: try parsing symbol directly
            const parsed = this.parseOCCSymbol(pos.symbol);
            return parsed ? parsed.optionType : 'C';
        },

        getDTE(pos, occ) {
            const expiry = pos.expires_at || pos.expiration;
            let exp = null;
            if (expiry) {
                exp = new Date(expiry);
            } else if (occ && occ.expiration) {
                exp = occ.expiration;
            } else {
                const parsed = this.parseOCCSymbol(pos.symbol);
                if (parsed) exp = parsed.expiration;
            }
            if (!exp) return 0;
            const now = new Date();
            return Math.max(0, Math.ceil((exp - now) / (1000 * 60 * 60 * 24)));
        },

        // ==================== CAPITAL AT RISK ====================
        // Spread-aware max risk: matches long/short legs into spreads
        // and computes actual max loss instead of raw notional.
        calcCapitalAtRisk(positions) {
            let totalRisk = 0;
            const equities = positions.filter(p => !p._isOption);
            const options = positions.filter(p => p._isOption);

            // Equity risk = full position value
            equities.forEach(p => {
                totalRisk += Math.abs(p._signedQty) * p._underlyingPrice;
            });

            // Group options by expiration (DTE) to match within same expiry
            const byExp = {};
            options.forEach(p => {
                const key = p._dte;
                if (!byExp[key]) byExp[key] = [];
                byExp[key].push(p);
            });

            for (const group of Object.values(byExp)) {
                const puts = group.filter(p => p._optionType === 'P');
                const calls = group.filter(p => p._optionType === 'C');
                totalRisk += this._matchSpreads(puts, 'P');
                totalRisk += this._matchSpreads(calls, 'C');
            }
            return totalRisk;
        },

        _matchSpreads(legs, type) {
            if (legs.length === 0) return 0;
            let risk = 0;
            // Clone with remaining qty tracker; include cost_basis for debit/credit detection
            // cost_basis sign: negative = paid (long), positive = received (short)
            const shorts = legs.filter(p => p._signedQty < 0)
                .map(p => ({ strike: p._strike, qty: Math.abs(p._signedQty), origQty: Math.abs(p._signedQty),
                    price: p._underlyingPrice, mktVal: Math.abs(parseFloat(p.market_value) || 0),
                    costBasis: parseFloat(p.cost_basis) || 0 }));
            const longs = legs.filter(p => p._signedQty > 0)
                .map(p => ({ strike: p._strike, qty: Math.abs(p._signedQty), origQty: Math.abs(p._signedQty),
                    price: p._underlyingPrice, mktVal: Math.abs(parseFloat(p.market_value) || 0),
                    costBasis: parseFloat(p.cost_basis) || 0 }));

            // Match each short with the closest available long to form a spread
            // Works for both credit and debit spreads (any direction)
            for (const s of shorts) {
                // Sort available longs by distance to this short's strike (closest first)
                const available = longs.filter(l => l.qty > 0 && l.strike !== s.strike);
                available.sort((a, b) => Math.abs(a.strike - s.strike) - Math.abs(b.strike - s.strike));

                for (const l of available) {
                    if (s.qty <= 0) break;
                    if (l.qty <= 0) continue;
                    const matched = Math.min(s.qty, l.qty);
                    const width = Math.abs(s.strike - l.strike);

                    // Use cost_basis to determine debit vs credit spread
                    // Per-contract cost (preserving sign): short is positive, long is negative
                    const sCostPer = s.costBasis / (s.origQty || 1);
                    const lCostPer = l.costBasis / (l.origQty || 1);
                    const netCost = (sCostPer + lCostPer) * matched;

                    if (netCost < 0) {
                        // Debit spread: max risk = net premium paid
                        risk += Math.abs(netCost);
                    } else {
                        // Credit spread: max risk = width - credit received
                        // Falls back to width-based if cost_basis is unavailable (0)
                        risk += Math.max(0, width * matched * 100 - netCost);
                    }

                    s.qty -= matched;
                    l.qty -= matched;
                }
                // Unmatched naked shorts
                if (s.qty > 0) {
                    risk += (type === 'P' ? s.strike : s.price) * s.qty * 100;
                }
            }
            // Unmatched long options: risk = premium paid (current market value)
            for (const l of longs) {
                if (l.qty > 0) risk += l.mktVal > 0 ? l.mktVal : 0;
            }
            return risk;
        },

        getSignedQty(pos) {
            const qty = Math.abs(parseFloat(pos.quantity) || 0);
            const dir = (pos.quantity_direction || '').toLowerCase();
            return dir === 'short' ? -qty : qty;
        },

        // ==================== BLACK-SCHOLES ====================
        normalCDF(x) {
            const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
            const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
            const sign = x < 0 ? -1 : 1;
            x = Math.abs(x) / Math.sqrt(2);
            const t = 1.0 / (1.0 + p * x);
            const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
            return 0.5 * (1.0 + sign * y);
        },

        normalPDF(x) {
            return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI);
        },

        bsGreeks(S, K, T, r, sigma, type) {
            if (T <= 0.0001 || sigma <= 0 || S <= 0 || K <= 0) {
                return { delta: 0, gamma: 0, theta: 0, vega: 0 };
            }
            const sqrtT = Math.sqrt(T);
            const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * sqrtT);
            const d2 = d1 - sigma * sqrtT;
            const nd1 = this.normalCDF(d1);
            const phid1 = this.normalPDF(d1);

            let delta, theta;
            if (type === 'C') {
                delta = nd1;
                theta = (-S * phid1 * sigma / (2 * sqrtT) - r * K * Math.exp(-r * T) * this.normalCDF(d2)) / 365;
            } else {
                delta = nd1 - 1;
                theta = (-S * phid1 * sigma / (2 * sqrtT) + r * K * Math.exp(-r * T) * this.normalCDF(-d2)) / 365;
            }
            const gamma = phid1 / (S * sigma * sqrtT);
            const vega = S * phid1 * sqrtT / 100;
            return { delta, gamma, theta, vega };
        },

        bsPrice(S, K, T, r, sigma, type) {
            if (T <= 0.0001) {
                return type === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0);
            }
            const sqrtT = Math.sqrt(T);
            const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * sqrtT);
            const d2 = d1 - sigma * sqrtT;
            if (type === 'C') {
                return S * this.normalCDF(d1) - K * Math.exp(-r * T) * this.normalCDF(d2);
            } else {
                return K * Math.exp(-r * T) * this.normalCDF(-d2) - S * this.normalCDF(-d1);
            }
        },

        // ==================== CHART RENDERING ====================
        renderAllCharts() {
            if (this.underlyingGroups.length === 0) return;
            this.renderDeltaChart();
            this.renderThetaChart();
            this.renderTreemapChart();
            this.renderScenarioChart();
        },

        renderDeltaChart() {
            const groups = [...this.underlyingGroups].sort((a, b) => Math.abs(b.deltaDollars) - Math.abs(a.deltaDollars)).slice(0, 15);
            const categories = groups.map(g => g.underlying);
            const values = groups.map(g => Math.round(g.deltaDollars));
            const colors = groups.map(g => g.deltaDollars >= 0 ? '#2ec4b6' : '#f77171');

            const options = {
                chart: { type: 'bar', height: 280, background: 'transparent', toolbar: { show: false },
                    animations: { enabled: true, easing: 'easeinout', speed: 400 } },
                series: [{ name: 'Delta $', data: values }],
                plotOptions: {
                    bar: {
                        horizontal: true, borderRadius: 3, barHeight: '70%',
                        colors: { ranges: [{ from: -9999999, to: -0.01, color: '#f77171' }, { from: 0, to: 9999999, color: '#2ec4b6' }] }
                    }
                },
                xaxis: {
                    categories: categories,
                    labels: { style: { colors: '#868c99', fontSize: '11px' },
                        formatter: v => '$' + this._shortNumber(v) }
                },
                yaxis: { labels: { style: { colors: '#d1d4dc', fontSize: '12px', fontWeight: 600 } } },
                grid: { borderColor: '#2a2e39', xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } } },
                tooltip: {
                    theme: 'dark',
                    y: { formatter: v => (v >= 0 ? '+$' : '-$') + formatNumber(Math.abs(v)) + ' delta exposure' }
                },
                dataLabels: { enabled: false },
            };

            if (this._charts.delta) {
                this._charts.delta.updateOptions(options, true, true);
            } else {
                this._charts.delta = new ApexCharts(document.querySelector('#chart-delta'), options);
                this._charts.delta.render();
            }
        },

        renderThetaChart() {
            const projection = this.calcThetaProjection();
            const options = {
                chart: { type: 'area', height: 280, background: 'transparent', toolbar: { show: false },
                    animations: { enabled: true, easing: 'easeinout', speed: 400 } },
                series: [{ name: 'Cumulative Theta', data: projection.cumulative }],
                xaxis: {
                    categories: projection.days,
                    labels: { style: { colors: '#868c99', fontSize: '11px' },
                        formatter: (v, i) => {
                            if (i === 0) return 'Today';
                            if (i % 7 === 0) return 'Day ' + v;
                            return '';
                        }
                    },
                    tickAmount: 7,
                },
                yaxis: {
                    labels: { style: { colors: '#868c99', fontSize: '11px' },
                        formatter: v => '$' + this._shortNumber(v) },
                },
                stroke: { curve: 'smooth', width: 2 },
                fill: {
                    type: 'gradient',
                    gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05,
                        stops: [0, 90, 100], colorStops: [
                            { offset: 0, color: '#2ec4b6', opacity: 0.4 },
                            { offset: 100, color: '#2ec4b6', opacity: 0.05 }
                        ] }
                },
                colors: ['#2ec4b6'],
                grid: { borderColor: '#2a2e39' },
                tooltip: {
                    theme: 'dark',
                    x: { formatter: (v) => 'Day ' + v },
                    y: { formatter: v => '+$' + formatNumber(v) + ' projected income' }
                },
                annotations: {
                    xaxis: projection.expirationMarkers.map(m => ({
                        x: m.day,
                        borderColor: '#868c99',
                        strokeDashArray: 4,
                        label: { text: m.label, style: { color: '#d1d4dc', background: '#2a2e39', fontSize: '10px' },
                            borderColor: '#2a2e39', orientation: 'horizontal', offsetY: -5 }
                    }))
                },
                dataLabels: { enabled: false },
            };

            if (this._charts.theta) {
                this._charts.theta.updateOptions(options, true, true);
            } else {
                this._charts.theta = new ApexCharts(document.querySelector('#chart-theta'), options);
                this._charts.theta.render();
            }
        },

        renderTreemapChart() {
            const groups = this.underlyingGroups.filter(g => g.maxRisk > 0);
            const data = groups.map(g => ({
                x: g.underlying + ' ($' + this._shortNumber(g.maxRisk) + ')',
                y: Math.round(g.maxRisk),
                fillColor: g.unrealizedPnl >= 0 ? '#2ec4b6' : '#f77171',
            }));

            const options = {
                chart: { type: 'treemap', height: 280, background: 'transparent', toolbar: { show: false },
                    animations: { enabled: true, speed: 400 } },
                series: [{ data: data }],
                plotOptions: {
                    treemap: {
                        distributed: true, enableShades: true, shadeIntensity: 0.3,
                        colorScale: { ranges: [] }, // Using fillColor per data point instead
                    }
                },
                legend: { show: false },
                tooltip: {
                    theme: 'dark',
                    y: {
                        formatter: (v, { dataPointIndex }) => {
                            const g = groups[dataPointIndex];
                            if (!g) return '$' + formatNumber(v);
                            return '$' + formatNumber(v) + ' max risk | P&L: ' +
                                (g.unrealizedPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(g.unrealizedPnl));
                        }
                    }
                },
                dataLabels: {
                    enabled: true,
                    style: { fontSize: '13px', fontWeight: 600, colors: ['#fff'] },
                    formatter: (text, op) => [text.split(' ')[0], '$' + this._shortNumber(op.value)],
                    offsetY: -2,
                },
            };

            if (this._charts.treemap) {
                this._charts.treemap.updateOptions(options, true, true);
            } else {
                this._charts.treemap = new ApexCharts(document.querySelector('#chart-treemap'), options);
                this._charts.treemap.render();
            }
        },

        renderScenarioChart() {
            const scenarios = this.calcScenarios();
            const options = {
                chart: { type: 'area', height: 280, background: 'transparent', toolbar: { show: false },
                    animations: { enabled: true, easing: 'easeinout', speed: 400 } },
                series: [{ name: 'Portfolio P&L Change', data: scenarios.pnl }],
                xaxis: {
                    categories: scenarios.labels,
                    labels: { style: { colors: '#868c99', fontSize: '11px' } },
                    axisBorder: { show: false },
                },
                yaxis: {
                    labels: { style: { colors: '#868c99', fontSize: '11px' },
                        formatter: v => (v >= 0 ? '+$' : '-$') + this._shortNumber(Math.abs(v)) },
                },
                stroke: { curve: 'smooth', width: 3 },
                fill: {
                    type: 'gradient',
                    gradient: {
                        shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05,
                        stops: [0, 90, 100],
                    }
                },
                colors: ['#2962ff'],
                grid: { borderColor: '#2a2e39' },
                annotations: {
                    yaxis: [{ y: 0, borderColor: '#868c99', strokeDashArray: 3,
                        label: { text: 'Break Even', style: { color: '#868c99', background: 'transparent', fontSize: '10px' } } }],
                    xaxis: [{ x: '0%', borderColor: '#868c99', strokeDashArray: 3,
                        label: { text: 'Current', style: { color: '#d1d4dc', background: '#2a2e39', fontSize: '10px' },
                            borderColor: '#2a2e39' } }]
                },
                tooltip: {
                    theme: 'dark',
                    y: { formatter: v => (v >= 0 ? '+$' : '-$') + formatNumber(Math.abs(v)) }
                },
                dataLabels: { enabled: false },
            };

            if (this._charts.scenario) {
                this._charts.scenario.updateOptions(options, true, true);
            } else {
                this._charts.scenario = new ApexCharts(document.querySelector('#chart-scenario'), options);
                this._charts.scenario.render();
            }
        },

        // ==================== THETA PROJECTION ====================
        calcThetaProjection() {
            const days = [];
            const dailyTheta = [];
            const cumulative = [];
            const expirationMarkers = [];
            const optionPositions = this.enrichedPositions.filter(p => p._isOption && p._dte > 0);
            const r = 0.045;
            let totalCum = 0;

            // Track unique expirations
            const expirations = {};
            optionPositions.forEach(p => {
                const dte = p._dte;
                if (dte > 0 && dte <= 45) {
                    if (!expirations[dte]) expirations[dte] = [];
                    expirations[dte].push(p._underlying);
                }
            });

            for (let day = 0; day <= 45; day++) {
                days.push(day);
                let dayTheta = 0;
                optionPositions.forEach(p => {
                    const remainingDTE = p._dte - day;
                    if (remainingDTE <= 0) return; // expired
                    const T = Math.max(remainingDTE, 0.5) / 365;
                    const iv = (p._iv || 30) / 100;
                    const greeks = this.bsGreeks(p._underlyingPrice, p._strike, T, r, iv, p._optionType);
                    dayTheta += greeks.theta * p._signedQty * 100;
                });
                totalCum += dayTheta;
                dailyTheta.push(Math.round(dayTheta * 100) / 100);
                cumulative.push(Math.round(totalCum * 100) / 100);

                // Mark expirations
                if (expirations[day]) {
                    const symbols = [...new Set(expirations[day])];
                    expirationMarkers.push({
                        day: day,
                        label: symbols.slice(0, 2).join(', ') + (symbols.length > 2 ? '...' : '') + ' exp'
                    });
                }
            }

            return { days, dailyTheta, cumulative, expirationMarkers };
        },

        // ==================== SCENARIO ANALYSIS ====================
        calcScenarios() {
            const moves = [-10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10];
            const labels = moves.map(m => (m >= 0 ? '+' : '') + m + '%');
            const pnl = [];
            const r = 0.045;

            moves.forEach(pctMove => {
                let totalPnlChange = 0;
                this.enrichedPositions.forEach(pos => {
                    const currentPrice = pos._underlyingPrice;
                    if (currentPrice <= 0) return;
                    const newPrice = currentPrice * (1 + pctMove / 100);

                    if (pos._isOption) {
                        const T = Math.max(pos._dte, 0.5) / 365;
                        const iv = (pos._iv || 30) / 100;
                        const currentOptPrice = this.bsPrice(currentPrice, pos._strike, T, r, iv, pos._optionType);
                        const newOptPrice = this.bsPrice(newPrice, pos._strike, T, r, iv, pos._optionType);
                        totalPnlChange += (newOptPrice - currentOptPrice) * pos._signedQty * 100;
                    } else {
                        totalPnlChange += (newPrice - currentPrice) * pos._signedQty;
                    }
                });
                pnl.push(Math.round(totalPnlChange));
            });

            return { labels, pnl };
        },

        // ==================== UTILITIES ====================
        onAccountChange() {
            localStorage.setItem('trade_journal_selected_account', this.selectedAccount || '');
            this.$nextTick(() => {
                this.subscribeToQuotes();
                this.renderAllCharts();
            });
        },

        toggleSort(col) {
            if (this.sortColumn === col) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = col;
                this.sortDirection = 'desc';
            }
        },

        formatDelta(v) {
            if (v == null || isNaN(v)) return '0.0';
            const sign = v >= 0 ? '+' : '';
            return sign + v.toFixed(1);
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

        _shortNumber(v) {
            v = Math.abs(v);
            if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M';
            if (v >= 1000) return (v / 1000).toFixed(1) + 'K';
            return v.toFixed(0);
        },

    }));
});
