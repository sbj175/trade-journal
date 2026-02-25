document.addEventListener('alpine:init', () => {
    Alpine.data('settingsApp', () => ({
        targets: [],
        saving: false,
        notification: null,
        _saveTimer: null,
        saveStatus: null,

        // Connection state
        connectionStatus: null,
        providerSecret: '',
        refreshToken: '',
        savingCredentials: false,
        deletingCredentials: false,

        // OAuth flow state
        onboarding: false,
        authEnabled: false,
        connecting: false,

        // Initial Sync date picker (default: 1 year ago, max: 2 years)
        syncStartDate: new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10),
        syncMinDate: new Date(Date.now() - 730 * 86400000).toISOString().slice(0, 10),
        syncMaxDate: new Date().toISOString().slice(0, 10),

        get syncDaysBack() {
            const start = new Date(this.syncStartDate);
            const now = new Date();
            return Math.max(1, Math.round((now - start) / 86400000));
        },

        get creditStrategies() {
            const names = ['Bull Put Spread', 'Bear Call Spread', 'Iron Condor', 'Iron Butterfly',
                           'Cash Secured Put', 'Covered Call', 'Short Put', 'Short Call',
                           'Short Strangle', 'Short Straddle'];
            return this.targets.filter(t => names.includes(t.strategy_name));
        },

        get debitStrategies() {
            const names = ['Bull Call Spread', 'Bear Put Spread', 'Long Call', 'Long Put',
                           'Long Strangle', 'Long Straddle'];
            return this.targets.filter(t => names.includes(t.strategy_name));
        },

        get equityStrategies() {
            const names = ['Shares'];
            return this.targets.filter(t => names.includes(t.strategy_name));
        },

        rollAlerts: { enabled: true, profitTarget: true, lossLimit: true, lateStage: true, deltaSaturation: true, lowRewardToRisk: true },
        privacyMode: 'off',
        activeTab: 'connection',
        initialSyncing: false,
        reprocessing: false,

        async init() {
            await Auth.requireAuth();

            // Parse URL query params
            const params = new URLSearchParams(window.location.search);
            if (params.get('tab')) this.activeTab = params.get('tab');
            this.onboarding = params.get('onboarding') === '1';
            this.authEnabled = Auth.isAuthEnabled();

            // Show error from OAuth callback redirect
            const errorParam = params.get('error');
            if (errorParam) this.showNotification(decodeURIComponent(errorParam), 'error');

            await this.checkConnection();
            await this.loadTargets();
            this.loadRollAlerts();
            this.privacyMode = localStorage.getItem('privacyMode') || 'off';
        },

        async checkConnection() {
            try {
                const resp = await Auth.authFetch('/api/connection/status');
                if (resp.ok) {
                    this.connectionStatus = await resp.json();
                }
            } catch (e) {
                this.connectionStatus = { connected: false, configured: false, error: 'Could not check connection status' };
            }
        },

        async connectTastytrade() {
            this.connecting = true;
            try {
                const resp = await Auth.authFetch('/api/auth/tastytrade/authorize', { method: 'POST' });
                if (resp.ok) {
                    const data = await resp.json();
                    window.location.href = data.authorization_url;
                    return;
                }
                const err = await resp.json().catch(() => ({}));
                this.showNotification(err.detail || 'Failed to start Tastytrade connection', 'error');
            } catch (e) {
                this.showNotification('Error: ' + e.message, 'error');
            }
            this.connecting = false;
        },

        async disconnectTastytrade() {
            if (!confirm('Disconnect your Tastytrade account? You will need to reconnect to sync trades.')) return;
            this.deletingCredentials = true;
            try {
                const resp = await Auth.authFetch('/api/auth/tastytrade/disconnect', { method: 'POST' });
                if (resp.ok) {
                    this.showNotification('Tastytrade disconnected', 'success');
                    await this.checkConnection();
                } else {
                    const data = await resp.json().catch(() => ({}));
                    this.showNotification(data.detail || 'Failed to disconnect', 'error');
                }
            } catch (e) {
                this.showNotification('Error: ' + e.message, 'error');
            }
            this.deletingCredentials = false;
        },

        async saveCredentials() {
            if (!this.providerSecret || !this.refreshToken) {
                this.showNotification('Please fill in both fields', 'error');
                return;
            }
            this.savingCredentials = true;
            try {
                // Save credentials to .env
                const saveResp = await Auth.authFetch('/api/settings/credentials', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider_secret: this.providerSecret,
                        refresh_token: this.refreshToken
                    })
                });
                if (!saveResp.ok) {
                    this.showNotification('Failed to save credentials', 'error');
                    this.savingCredentials = false;
                    return;
                }

                // Reconnect with new credentials
                const reconnResp = await Auth.authFetch('/api/connection/reconnect', { method: 'POST' });
                if (reconnResp.ok) {
                    this.connectionStatus = await reconnResp.json();
                    if (this.connectionStatus.connected) {
                        this.showNotification('Connected to Tastytrade successfully!', 'success');
                        this.providerSecret = '';
                        this.refreshToken = '';
                    } else {
                        this.showNotification('Credentials saved but connection failed: ' + (this.connectionStatus.error || 'Unknown error'), 'error');
                    }
                } else {
                    this.showNotification('Failed to reconnect', 'error');
                }
            } catch (e) {
                this.showNotification('Error saving credentials: ' + e.message, 'error');
            }
            this.savingCredentials = false;
        },

        async deleteCredentials() {
            if (!confirm('Remove your Tastytrade credentials? You will need to re-enter them to sync.')) return;
            this.deletingCredentials = true;
            try {
                const resp = await Auth.authFetch('/api/settings/credentials', { method: 'DELETE' });
                if (resp.ok) {
                    this.showNotification('Credentials removed', 'success');
                    await this.checkConnection();
                } else {
                    const data = await resp.json().catch(() => ({}));
                    this.showNotification(data.detail || 'Failed to remove credentials', 'error');
                }
            } catch (e) {
                this.showNotification('Error removing credentials: ' + e.message, 'error');
            }
            this.deletingCredentials = false;
        },

        async loadTargets() {
            try {
                const resp = await Auth.authFetch('/api/settings/targets');
                if (resp.ok) {
                    this.targets = await resp.json();
                }
            } catch (e) {
                this.showNotification('Failed to load targets', 'error');
            }
        },

        debouncedSaveTargets() {
            if (this._saveTimer) clearTimeout(this._saveTimer);
            this.saveStatus = 'pending';
            this._saveTimer = setTimeout(() => this.saveTargets(), 800);
        },

        async saveTargets() {
            this.saveStatus = 'saving';
            try {
                const payload = this.targets.map(t => ({
                    strategy_name: t.strategy_name,
                    profit_target_pct: parseFloat(t.profit_target_pct),
                    loss_target_pct: parseFloat(t.loss_target_pct)
                }));
                const resp = await Auth.authFetch('/api/settings/targets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (resp.ok) {
                    this.saveStatus = 'saved';
                    setTimeout(() => { if (this.saveStatus === 'saved') this.saveStatus = null; }, 2000);
                } else {
                    this.showNotification('Failed to save targets', 'error');
                    this.saveStatus = null;
                }
            } catch (e) {
                this.showNotification('Failed to save targets', 'error');
                this.saveStatus = null;
            }
        },

        async resetToDefaults() {
            try {
                const resp = await Auth.authFetch('/api/settings/targets/reset', { method: 'POST' });
                if (resp.ok) {
                    await this.loadTargets();
                    this.showNotification('Targets reset to defaults', 'success');
                } else {
                    this.showNotification('Failed to reset targets', 'error');
                }
            } catch (e) {
                this.showNotification('Failed to reset targets', 'error');
            }
        },

        loadRollAlerts() {
            try {
                const saved = localStorage.getItem('rollAlertSettings');
                if (saved) this.rollAlerts = JSON.parse(saved);
            } catch (e) { /* use defaults */ }
        },

        saveRollAlerts() {
            localStorage.setItem('rollAlertSettings', JSON.stringify(this.rollAlerts));
            this.saveStatus = 'saved';
            setTimeout(() => { if (this.saveStatus === 'saved') this.saveStatus = null; }, 2000);
        },

        savePrivacyMode() {
            localStorage.setItem('privacyMode', this.privacyMode);
            this.saveStatus = 'saved';
            setTimeout(() => { if (this.saveStatus === 'saved') this.saveStatus = null; }, 2000);
        },

        async initialSync() {
            const days = this.syncDaysBack;
            const msg = this.onboarding
                ? `This will import ${days} days of trading history from Tastytrade.\n\nThis may take a minute. Continue?`
                : `Initial Sync will CLEAR the existing database and rebuild from scratch.\n\nThis will fetch ${days} days of transactions and may take several minutes.\n\nAre you sure you want to continue?`;
            if (!confirm(msg)) return;

            this.initialSyncing = true;
            try {
                const response = await Auth.authFetch('/api/sync/initial', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ start_date: this.syncStartDate })
                });
                if (!response.ok) throw new Error(`Initial sync failed: ${response.statusText}`);
                const result = await response.json();

                if (this.onboarding) {
                    // Onboarding complete — go to Positions page
                    window.location.href = '/positions';
                    return;
                }
                this.showNotification(
                    `Initial sync completed! ${result.transactions_processed || 0} transactions, ` +
                    `${result.orders_saved || 0} orders in ${result.chains_saved || 0} chains`, 'success'
                );
            } catch (error) {
                this.showNotification('Initial sync failed: ' + error.message, 'error');
            } finally {
                this.initialSyncing = false;
            }
        },

        async reprocessChains() {
            this.reprocessing = true;
            try {
                const response = await Auth.authFetch('/api/reprocess-chains', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (!response.ok) throw new Error(`Reprocessing failed: ${response.statusText}`);
                await response.json();
                this.showNotification('Chain reprocessing completed successfully!', 'success');
            } catch (error) {
                this.showNotification('Reprocessing failed: ' + error.message, 'error');
            } finally {
                this.reprocessing = false;
            }
        },

        showNotification(message, type) {
            this.notification = { message, type };
            setTimeout(() => { this.notification = null; }, 3000);
        }
    }));
});
