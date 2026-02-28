/**
 * OptionLedger Admin Dashboard — Alpine.js component
 */
function adminApp() {
    return {
        // Auth state
        authenticated: false,
        passphrase: '',
        authError: '',

        // Data
        stats: { total_users: 0, active_users: 0, tt_connected: 0, total_accounts: 0 },
        users: [],
        dbHealth: null,
        waitlist: [],
        loading: false,

        // Sorting
        sortColumn: 'last_login_at',
        sortDirection: 'desc',

        // Expandable row
        expandedUser: null,

        // Delete confirmation modal
        deleteModal: { open: false, user: null, confirmEmail: '' },

        // Delete user confirmation modal
        deleteUserModal: { open: false, user: null, confirmEmail: '' },

        get secret() {
            return sessionStorage.getItem('admin_secret') || '';
        },

        get sortedUsers() {
            const col = this.sortColumn;
            const dir = this.sortDirection === 'asc' ? 1 : -1;
            return [...this.users].sort((a, b) => {
                let va = a[col];
                let vb = b[col];
                // Nulls always sort last
                if (va == null && vb == null) return 0;
                if (va == null) return 1;
                if (vb == null) return -1;
                // Booleans: true > false
                if (typeof va === 'boolean') {
                    return (va === vb) ? 0 : (va ? -1 : 1) * dir;
                }
                // Numbers
                if (typeof va === 'number') {
                    return (va - vb) * dir;
                }
                // Strings (dates sort correctly as ISO strings)
                return String(va).localeCompare(String(vb)) * dir;
            });
        },

        toggleSort(column) {
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                this.sortDirection = 'asc';
            }
        },

        sortIcon(column) {
            if (this.sortColumn !== column) return '';
            return this.sortDirection === 'asc' ? ' \u25B2' : ' \u25BC';
        },

        async init() {
            const saved = sessionStorage.getItem('admin_secret');
            if (saved) {
                const ok = await this.verifySecret(saved);
                if (ok) {
                    this.authenticated = true;
                    await this.loadData();
                } else {
                    sessionStorage.removeItem('admin_secret');
                }
            }
        },

        async verifySecret(secret) {
            try {
                const res = await fetch('/api/admin/health', {
                    headers: { 'X-Admin-Secret': secret },
                });
                return res.ok;
            } catch {
                return false;
            }
        },

        async login() {
            this.authError = '';
            if (!this.passphrase.trim()) {
                this.authError = 'Passphrase is required';
                return;
            }
            const ok = await this.verifySecret(this.passphrase);
            if (ok) {
                sessionStorage.setItem('admin_secret', this.passphrase);
                this.authenticated = true;
                this.passphrase = '';
                await this.loadData();
            } else {
                this.authError = 'Invalid passphrase';
            }
        },

        logout() {
            sessionStorage.removeItem('admin_secret');
            this.authenticated = false;
            this.stats = { total_users: 0, active_users: 0, tt_connected: 0, total_accounts: 0 };
            this.users = [];
        },

        async apiFetch(path, options = {}) {
            const headers = {
                'X-Admin-Secret': this.secret,
                'Content-Type': 'application/json',
                ...(options.headers || {}),
            };
            const res = await fetch(path, { ...options, headers });
            if (res.status === 401) {
                this.logout();
                return null;
            }
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body.detail || body.error || `HTTP ${res.status}`);
            }
            return res.json();
        },

        async loadData() {
            this.loading = true;
            try {
                const [statsData, usersData, dbHealthData, waitlistData] = await Promise.all([
                    this.apiFetch('/api/admin/stats'),
                    this.apiFetch('/api/admin/users'),
                    this.apiFetch('/api/admin/db-health'),
                    this.apiFetch('/api/admin/waitlist'),
                ]);
                if (statsData) this.stats = statsData;
                if (usersData) this.users = usersData;
                if (dbHealthData) this.dbHealth = dbHealthData;
                if (waitlistData) this.waitlist = waitlistData;
            } catch (err) {
                console.error('Failed to load data:', err);
            } finally {
                this.loading = false;
            }
        },

        async reprocessChains(user) {
            if (!confirm(`Reprocess chains for ${user.email || user.id}? This will rebuild order chains from existing transactions.`)) return;
            try {
                const result = await this.apiFetch(`/api/admin/users/${user.id}/reprocess-chains`, { method: 'POST' });
                alert(`Reprocess complete: ${result.orders_processed} orders, ${result.chains_created} chains`);
                await this.loadData();
            } catch (err) {
                alert('Reprocess failed: ' + err.message);
            }
        },

        async resetSync(user) {
            if (!confirm(`Reset sync metadata for ${user.email || user.id}? This will force a full re-sync on their next login.`)) return;
            try {
                await this.apiFetch(`/api/admin/users/${user.id}/reset-sync`, { method: 'POST' });
                await this.loadData();
            } catch (err) {
                alert('Failed: ' + err.message);
            }
        },

        openDeleteModal(user) {
            this.deleteModal = { open: true, user, confirmEmail: '' };
        },

        closeDeleteModal() {
            this.deleteModal = { open: false, user: null, confirmEmail: '' };
        },

        get canConfirmDelete() {
            if (!this.deleteModal.user) return false;
            const target = this.deleteModal.user.email || this.deleteModal.user.id;
            return this.deleteModal.confirmEmail === target;
        },

        async confirmDeleteData() {
            if (!this.canConfirmDelete) return;
            const user = this.deleteModal.user;
            try {
                await this.apiFetch(`/api/admin/users/${user.id}/data`, { method: 'DELETE' });
                this.closeDeleteModal();
                await this.loadData();
            } catch (err) {
                alert('Failed: ' + err.message);
            }
        },

        openDeleteUserModal(user) {
            this.deleteUserModal = { open: true, user, confirmEmail: '' };
        },

        closeDeleteUserModal() {
            this.deleteUserModal = { open: false, user: null, confirmEmail: '' };
        },

        get canConfirmDeleteUser() {
            if (!this.deleteUserModal.user) return false;
            const target = this.deleteUserModal.user.email || this.deleteUserModal.user.id;
            return this.deleteUserModal.confirmEmail === target;
        },

        async confirmDeleteUser() {
            if (!this.canConfirmDeleteUser) return;
            const user = this.deleteUserModal.user;
            try {
                await this.apiFetch(`/api/admin/users/${user.id}`, { method: 'DELETE' });
                this.closeDeleteUserModal();
                await this.loadData();
            } catch (err) {
                alert('Failed: ' + err.message);
            }
        },

        formatDate(dateStr) {
            if (!dateStr) return '-';
            try {
                const d = new Date(dateStr);
                return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
            } catch {
                return dateStr;
            }
        },

        formatDateTime(dateStr) {
            if (!dateStr) return '-';
            try {
                const d = new Date(dateStr);
                return d.toLocaleString('en-US', {
                    month: 'short', day: 'numeric', year: 'numeric',
                    hour: 'numeric', minute: '2-digit',
                });
            } catch {
                return dateStr;
            }
        },

        formatNumber(n) {
            if (n == null) return '-';
            return n.toLocaleString();
        },

        formatBytes(bytes) {
            if (bytes == null) return '-';
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let i = 0;
            let val = bytes;
            while (val >= 1024 && i < units.length - 1) {
                val /= 1024;
                i++;
            }
            return val.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
        },
    };
}
