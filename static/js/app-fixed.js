// Trade Journal Alpine.js Application - Fixed Version
function tradeJournal() {
    return {
        // State
        trades: [],
        accounts: [],
        selectedAccount: '',
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
        syncing: false,
        initialSyncing: false,
        
        // Filters
        searchTerm: '',
        filterStatus: '',
        filterStrategy: '',
        filterUnderlying: '',
        syncDays: 30,
        
        // Sorting
        sortColumn: 'entry_date',
        sortDirection: 'desc',
        
        // Modal state
        editModalOpen: false,
        editingTrade: null,
        
        // Trade details modal state
        tradeDetailsModalOpen: false,
        loadingTradeDetails: false,
        tradeDetails: null,
        
        // Initialize
        async init() {
            console.log('Initializing Trade Journal...');
            await this.loadAccounts();
            await this.loadDashboard();
            await this.loadTrades();
        },
        
        // Load accounts
        async loadAccounts() {
            try {
                console.log('Loading accounts...');
                const response = await fetch('/api/accounts');
                const data = await response.json();
                this.accounts = data.accounts || [];
                
                // Set default account (first one)
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
            await this.loadDashboard();
            await this.loadTrades();
        },
        
        // Format number with commas
        formatNumber(num) {
            if (num === null || num === undefined) return '0.00';
            return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
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
        async loadTrades() {
            this.loading = true;
            try {
                console.log('Loading trades...');
                const params = new URLSearchParams();
                if (this.selectedAccount) params.append('account_number', this.selectedAccount);
                if (this.filterStatus) params.append('status', this.filterStatus);
                if (this.filterStrategy) params.append('strategy', this.filterStrategy);
                if (this.filterUnderlying) params.append('underlying', this.filterUnderlying);
                
                const response = await fetch(`/api/trades?${params}`);
                const data = await response.json();
                this.trades = data.trades || [];
                
                // Manually render trades to avoid Alpine.js issues
                this.renderTrades();
            } catch (error) {
                console.error('Error loading trades:', error);
            } finally {
                this.loading = false;
            }
        },
        
        // Manually render trades table
        renderTrades() {
            const tbody = document.getElementById('tradesTableBody');
            if (!tbody) return;
            
            // Clear existing rows
            tbody.innerHTML = '';
            
            // Add new rows
            this.trades.forEach(trade => {
                const row = document.createElement('tr');
                row.className = 'hover:bg-slate-800/30 transition-colors';
                
                const statusClass = trade.status === 'Closed' ? 'bg-green-900/30 text-green-400' :
                                  trade.status === 'Open' ? 'bg-orange-900/30 text-orange-400' :
                                  'bg-blue-900/30 text-blue-400';
                
                const pnlClass = (trade.current_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400';
                
                row.innerHTML = `
                    <td class="px-6 py-4 text-sm font-mono">
                        <button data-trade-id="${trade.trade_id}" class="view-trade-btn text-blue-400 hover:text-blue-300 hover:underline cursor-pointer" title="View Trade Details">
                            ${trade.trade_id}
                        </button>
                    </td>
                    <td class="px-6 py-4 text-sm font-semibold">${trade.underlying}</td>
                    <td class="px-6 py-4 text-sm">
                        <span class="px-2 py-1 bg-purple-900/30 text-purple-400 rounded-md">${trade.strategy_type}</span>
                    </td>
                    <td class="px-6 py-4 text-sm">${this.formatDate(trade.entry_date)}</td>
                    <td class="px-6 py-4 text-sm">
                        <span class="px-2 py-1 rounded-md ${statusClass}">${trade.status}</span>
                    </td>
                    <td class="px-6 py-4 text-sm font-semibold">
                        <span class="${pnlClass}">$${this.formatNumber(trade.current_pnl || 0)}</span>
                    </td>
                    <td class="px-6 py-4 text-sm">
                        <span class="text-slate-400 text-xs">${trade.current_notes ? trade.current_notes.substring(0, 30) + (trade.current_notes.length > 30 ? '...' : '') : 'No comments'}</span>
                    </td>
                    <td class="px-6 py-4 text-sm">
                        <button data-trade-id="${trade.trade_id}" class="edit-trade-btn text-blue-400 hover:text-blue-300 mr-2" title="Edit">
                            <i class="fas fa-edit"></i>
                        </button>
                    </td>
                `;
                
                tbody.appendChild(row);
            });
            
            // Add click handlers for buttons
            document.querySelectorAll('.edit-trade-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const tradeId = e.currentTarget.dataset.tradeId;
                    this.openEditModal(tradeId);
                });
            });
            
            document.querySelectorAll('.view-trade-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const tradeId = e.currentTarget.dataset.tradeId;
                    this.openTradeDetailsModal(tradeId);
                });
            });
        },
        
        // Search trades
        async searchTrades() {
            if (!this.searchTerm) {
                await this.loadTrades();
                return;
            }
            
            this.loading = true;
            try {
                let url = `/api/search?q=${encodeURIComponent(this.searchTerm)}`;
                if (this.selectedAccount) {
                    url += `&account_number=${encodeURIComponent(this.selectedAccount)}`;
                }
                
                const response = await fetch(url);
                const data = await response.json();
                this.trades = data.results || [];
                this.renderTrades();
            } catch (error) {
                console.error('Error searching trades:', error);
            } finally {
                this.loading = false;
            }
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
                    body: JSON.stringify({ days_back: parseInt(this.syncDays) })
                });
                
                if (!response.ok) {
                    throw new Error(`Sync failed: ${response.statusText}`);
                }
                
                const result = await response.json();
                console.log('Sync completed:', result);
                
                // Reload data including accounts
                await this.loadAccounts();
                await this.loadDashboard();
                await this.loadTrades();
                
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
                await this.loadTrades();
                
            } catch (error) {
                console.error('Error during initial sync:', error);
                alert('Initial sync failed: ' + error.message);
            } finally {
                this.initialSyncing = false;
            }
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
        
        // Open edit modal
        openEditModal(tradeId) {
            const trade = this.trades.find(t => t.trade_id === tradeId);
            if (!trade) return;
            
            this.editingTrade = trade;
            
            // Populate modal fields
            document.getElementById('editTradeId').value = trade.trade_id;
            document.getElementById('displayTradeId').textContent = trade.trade_id;
            document.getElementById('displayUnderlying').textContent = trade.underlying;
            document.getElementById('displayStrategy').textContent = trade.strategy_type;
            document.getElementById('editStatus').value = trade.status;
            document.getElementById('editComments').value = trade.current_notes || '';
            document.getElementById('editTags').value = (trade.tags || []).join(', ');
            
            // Show modal
            this.editModalOpen = true;
            document.getElementById('editModal').classList.remove('hidden');
        },
        
        // Close edit modal
        closeEditModal() {
            console.log('Closing modal...');
            this.editModalOpen = false;
            this.editingTrade = null;
            document.getElementById('editModal').classList.add('hidden');
        },
        
        // Save trade changes
        async saveTradeChanges() {
            console.log('Saving trade changes...');
            const tradeId = document.getElementById('editTradeId').value;
            const status = document.getElementById('editStatus').value;
            const comments = document.getElementById('editComments').value;
            const tagsInput = document.getElementById('editTags').value;
            const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];
            
            try {
                const response = await fetch(`/api/trades/${tradeId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        trade_id: tradeId,
                        status: status,
                        current_notes: comments,
                        tags: tags
                    })
                });
                
                if (!response.ok) {
                    throw new Error('Failed to update trade');
                }
                
                // Close modal
                this.closeEditModal();
                
                // Reload trades
                await this.loadTrades();
                
                // Update dashboard if status changed
                await this.loadDashboard();
                
            } catch (error) {
                console.error('Error saving trade:', error);
                alert('Failed to save changes: ' + error.message);
            }
        },
        
        // Open trade details modal
        async openTradeDetailsModal(tradeId) {
            console.log('Opening trade details for:', tradeId);
            this.tradeDetailsModalOpen = true;
            this.loadingTradeDetails = true;
            this.tradeDetails = null;
            
            // Show modal
            document.getElementById('tradeDetailsModal').classList.remove('hidden');
            
            try {
                const response = await fetch(`/api/trades/${tradeId}`);
                if (!response.ok) {
                    throw new Error(`Failed to fetch trade details: ${response.statusText}`);
                }
                
                this.tradeDetails = await response.json();
                
                // Sort option legs by strike price (ascending)
                if (this.tradeDetails.option_legs) {
                    this.tradeDetails.option_legs.sort((a, b) => a.strike - b.strike);
                }
                
                console.log('Loaded trade details:', this.tradeDetails);
                
            } catch (error) {
                console.error('Error loading trade details:', error);
                alert('Failed to load trade details: ' + error.message);
                this.closeTradeDetailsModal();
            } finally {
                this.loadingTradeDetails = false;
            }
        },
        
        // Close trade details modal
        closeTradeDetailsModal() {
            console.log('Closing trade details modal...');
            this.tradeDetailsModalOpen = false;
            this.tradeDetails = null;
            this.loadingTradeDetails = false;
            document.getElementById('tradeDetailsModal').classList.add('hidden');
        }
    };
}

