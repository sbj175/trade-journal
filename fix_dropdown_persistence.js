// Enhanced state persistence for Trade Journal
// This fixes dropdown value persistence on page refresh

function enhancedTradeJournal() {
    return {
        ...tradeJournal(),
        
        // Override init to properly restore dropdowns
        async init() {
            console.log('Initializing Trade Journal with enhanced persistence...');
            
            // Get saved state before anything else
            const savedState = this.getSavedState();
            console.log('Found saved state:', savedState);
            
            // Load accounts first
            await this.loadAccounts();
            
            // Apply saved account after accounts are loaded
            if (savedState && savedState.selectedAccount) {
                // Use setTimeout to ensure Alpine has rendered the options
                setTimeout(() => {
                    if (this.accounts.some(a => a.account_number === savedState.selectedAccount)) {
                        this.selectedAccount = savedState.selectedAccount;
                        console.log('Applied saved account:', savedState.selectedAccount);
                    }
                }, 100);
            }
            
            // Load other data
            await this.loadDashboard();
            await this.loadAvailableUnderlyings();
            
            // Apply saved underlying after underlyings are loaded
            if (savedState && savedState.filterUnderlying) {
                setTimeout(() => {
                    if (this.availableUnderlyings.includes(savedState.filterUnderlying)) {
                        this.filterUnderlying = savedState.filterUnderlying;
                        console.log('Applied saved underlying:', savedState.filterUnderlying);
                    }
                }, 100);
            }
            
            // Apply other saved filters
            if (savedState) {
                this.filterStrategy = savedState.filterStrategy || '';
                this.filterStatus = savedState.filterStatus || '';
                this.syncDays = savedState.syncDays || 30;
                this.sortColumn = savedState.sortColumn || 'underlying';
                this.sortDirection = savedState.sortDirection || 'asc';
            }
            
            await this.loadTrades();
            await this.loadChains();
        },
        
        // Helper to get saved state
        getSavedState() {
            try {
                const savedState = localStorage.getItem('tradeJournalState');
                return savedState ? JSON.parse(savedState) : null;
            } catch (error) {
                console.error('Error getting saved state:', error);
                return null;
            }
        }
    };
}