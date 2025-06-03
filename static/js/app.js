// Trade Journal Alpine.js Application
function tradeJournal() {
    return {
        // State
        trades: [],
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
        selectedTrade: null,
        editingTrade: null,
        editingNotes: '',
        
        // UI State
        loading: false,
        syncing: false,
        showTradeModal: false,
        showNotesModal: false,
        
        // Filters
        searchTerm: '',
        filterStatus: '',
        filterStrategy: '',
        filterUnderlying: '',
        syncDays: 30,
        
        // Charts
        pnlChart: null,
        strategyChart: null,
        
        // Initialize
        async init() {
            await this.loadDashboard();
            await this.loadTrades();
            this.initCharts();
        },
        
        // Format number with commas
        formatNumber(num) {
            if (num === null || num === undefined) return '0.00';
            return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        },
        
        // Format date
        formatDate(dateStr) {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', { 
                year: 'numeric', 
                month: 'short', 
                day: 'numeric' 
            });
        },
        
        // Load dashboard data
        async loadDashboard() {
            try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();
                this.dashboard = data;
                this.updateCharts();
            } catch (error) {
                console.error('Error loading dashboard:', error);
                this.showNotification('Failed to load dashboard', 'error');
            }
        },
        
        // Load trades
        async loadTrades() {
            this.loading = true;
            try {
                const params = new URLSearchParams();
                if (this.filterStatus) params.append('status', this.filterStatus);
                if (this.filterStrategy) params.append('strategy', this.filterStrategy);
                if (this.filterUnderlying) params.append('underlying', this.filterUnderlying);
                
                const response = await fetch(`/api/trades?${params}`);
                const data = await response.json();
                this.trades = data.trades;
            } catch (error) {
                console.error('Error loading trades:', error);
                this.showNotification('Failed to load trades', 'error');
            } finally {
                this.loading = false;
            }
        },
        
        // Search trades
        async searchTrades() {
            if (!this.searchTerm) {
                await this.loadTrades();
                return;
            }
            
            this.loading = true;
            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(this.searchTerm)}`);
                const data = await response.json();
                this.trades = data.results;
            } catch (error) {
                console.error('Error searching trades:', error);
                this.showNotification('Search failed', 'error');
            } finally {
                this.loading = false;
            }
        },
        
        // Sync trades from Tastytrade
        async syncTrades() {
            this.syncing = true;
            try {
                const response = await fetch('/api/sync', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ days_back: parseInt(this.syncDays) })
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || `Sync failed: ${response.statusText}`);
                }
                
                const result = await response.json();
                console.log('Sync result:', result);
                
                // Show detailed sync results
                const message = `Sync completed: ${result.trades_saved} trades saved` +
                    (result.trades_failed > 0 ? `, ${result.trades_failed} failed` : '') +
                    `, ${result.positions_updated} positions updated`;
                
                this.showNotification(message, 'success');
                
                // Reload data
                await this.loadDashboard();
                await this.loadTrades();
                
            } catch (error) {
                console.error('Error syncing trades:', error);
                this.showNotification('Sync failed: ' + error.message, 'error');
            } finally {
                this.syncing = false;
            }
        },
        
        // View trade details
        async viewTradeDetails(tradeId) {
            try {
                const response = await fetch(`/api/trades/${tradeId}`);
                const trade = await response.json();
                this.selectedTrade = trade;
                this.showTradeModal = true;
            } catch (error) {
                console.error('Error loading trade details:', error);
                this.showNotification('Failed to load trade details', 'error');
            }
        },
        
        // Edit notes
        editNotes(trade) {
            this.editingTrade = trade;
            this.editingNotes = trade.current_notes || '';
            this.showNotesModal = true;
        },
        
        // Save notes
        async saveNotes() {
            try {
                const response = await fetch(`/api/trades/${this.editingTrade.trade_id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        trade_id: this.editingTrade.trade_id,
                        current_notes: this.editingNotes
                    })
                });
                
                if (response.ok) {
                    this.editingTrade.current_notes = this.editingNotes;
                    this.showNotesModal = false;
                    this.showNotification('Notes saved', 'success');
                }
            } catch (error) {
                console.error('Error saving notes:', error);
                this.showNotification('Failed to save notes', 'error');
            }
        },
        
        // Update trade status
        async updateTradeStatus(trade) {
            const newStatus = prompt('Enter new status (Open, Closed, Rolled):', trade.status);
            if (!newStatus) return;
            
            try {
                const response = await fetch(`/api/trades/${trade.trade_id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        trade_id: trade.trade_id,
                        status: newStatus
                    })
                });
                
                if (response.ok) {
                    trade.status = newStatus;
                    this.showNotification('Status updated', 'success');
                    await this.loadDashboard();
                }
            } catch (error) {
                console.error('Error updating status:', error);
                this.showNotification('Failed to update status', 'error');
            }
        },
        
        // Initialize charts
        initCharts() {
            // P&L Chart
            const pnlCtx = document.getElementById('pnlChart').getContext('2d');
            this.pnlChart = new Chart(pnlCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Monthly P&L',
                        data: [],
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        tension: 0.4,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            grid: {
                                color: 'rgba(71, 85, 105, 0.3)'
                            },
                            ticks: {
                                color: '#cbd5e1',
                                callback: function(value) {
                                    return '$' + value.toLocaleString();
                                }
                            }
                        },
                        x: {
                            grid: {
                                color: 'rgba(71, 85, 105, 0.3)'
                            },
                            ticks: {
                                color: '#cbd5e1'
                            }
                        }
                    }
                }
            });
            
            // Strategy Chart
            const strategyCtx = document.getElementById('strategyChart').getContext('2d');
            this.strategyChart = new Chart(strategyCtx, {
                type: 'doughnut',
                data: {
                    labels: [],
                    datasets: [{
                        data: [],
                        backgroundColor: [
                            '#3b82f6',
                            '#8b5cf6',
                            '#10b981',
                            '#f59e0b',
                            '#ef4444'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                color: '#cbd5e1',
                                padding: 20
                            }
                        }
                    }
                }
            });
        },
        
        // Update charts with data
        async updateCharts() {
            // Update P&L chart
            try {
                const response = await fetch('/api/performance/monthly');
                const data = await response.json();
                
                const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                
                this.pnlChart.data.labels = data.months.map(m => months[parseInt(m.month) - 1]);
                this.pnlChart.data.datasets[0].data = data.months.map(m => m.total_pnl || 0);
                this.pnlChart.update();
            } catch (error) {
                console.error('Error updating P&L chart:', error);
            }
            
            // Update strategy chart
            if (this.dashboard.strategy_breakdown) {
                this.strategyChart.data.labels = this.dashboard.strategy_breakdown.map(s => s.strategy_type);
                this.strategyChart.data.datasets[0].data = this.dashboard.strategy_breakdown.map(s => s.count);
                this.strategyChart.update();
            }
        },
        
        // Show notification
        showNotification(message, type = 'info') {
            console.log(`${type}: ${message}`);
            
            // Simple console log for now to avoid DOM manipulation issues
            if (type === 'error') {
                console.error(message);
                alert('Error: ' + message);
            } else {
                console.info(message);
            }
        }
    };
}