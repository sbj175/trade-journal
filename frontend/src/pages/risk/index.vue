<script setup>
import { onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber } from '@/lib/formatters'
import { formatDelta, shortNumber, getAccountSymbol as _getAccountSymbol } from '@/lib/riskCalculations'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useRiskData } from '@/composables/useRiskData'
import { useRiskCharts } from '@/composables/useRiskCharts'

const Auth = useAuth()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()

// ==================== DATA COMPOSABLE ====================
const {
  accounts, selectedAccount, isLoading, error,
  liveQuotesActive, greeksSource, sortColumn, sortDirection,
  allPositions, enrichedPositions, underlyingGroups, sortedGroups,
  portfolioTotals, currentBalance, bpUtilization,
  fetchData, connectWebSocket, disconnectWebSocket,
  setOnQuoteUpdate, toggleSort, onAccountChange,
} = useRiskData(Auth)

// ==================== CHARTS COMPOSABLE ====================
const {
  ensureApexCharts, destroyCharts, debouncedUpdateCharts, renderAllCharts,
} = useRiskCharts({ underlyingGroups, enrichedPositions })

// ==================== WIRING ====================
setOnQuoteUpdate(debouncedUpdateCharts)

function getAccountSymbol(accountNumber) {
  return _getAccountSymbol(accounts.value, accountNumber)
}

function handleAccountChange() {
  onAccountChange(renderAllCharts)
}

// Watch account store for changes from GlobalToolbar
watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  handleAccountChange()
})

// Watch sync store — refetch when sync completes
watch(() => syncStore.lastSyncTime, async (val) => {
  if (val) {
    await fetchData()
    await nextTick()
    if (allPositions.value.length > 0) renderAllCharts()
  }
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  try { await ensureApexCharts() } catch (e) { }
  await fetchData()
  selectedAccount.value = accountsStore.selectedAccount
  connectWebSocket()
  await nextTick()
  if (allPositions.value.length > 0) renderAllCharts()
})

onUnmounted(() => {
  disconnectWebSocket()
  destroyCharts()
})

</script>

<template>
  <!-- Status Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center justify-between text-sm">
    <div class="flex items-center gap-6">
      <span class="text-tv-muted">
        <i class="fas fa-shield-halved mr-1 text-tv-blue"></i>Portfolio Risk X-Ray
      </span>
      <span v-if="enrichedPositions.length > 0" class="text-tv-muted">
        <span class="text-tv-text">{{ enrichedPositions.length }}</span> positions across
        <span class="text-tv-text">{{ underlyingGroups.length }}</span> underlyings
      </span>
    </div>
    <div class="flex items-center gap-4">
      <span class="flex items-center gap-2">
        <span class="pulse-dot" :class="liveQuotesActive ? 'bg-tv-green' : 'bg-tv-red'"></span>
        <span class="text-tv-muted">{{ liveQuotesActive ? 'Live' : 'Offline' }}</span>
      </span>
      <span v-if="greeksSource" class="text-tv-muted">
        Greeks: <span class="text-tv-text">{{ greeksSource }}</span>
      </span>
    </div>
  </div>

  <!-- Loading State -->
  <div v-if="isLoading" class="text-center py-24">
    <div class="spinner mx-auto mb-4" style="width: 48px; height: 48px; border-width: 4px;"></div>
    <p class="text-tv-muted text-lg">Calculating portfolio risk...</p>
  </div>

  <!-- Empty State -->
  <div v-else-if="allPositions.length === 0" class="text-center py-24">
    <i class="fas fa-shield-halved text-6xl text-tv-border mb-6"></i>
    <p class="text-tv-muted text-xl mb-2">No open positions found</p>
    <p class="text-tv-muted">Sync your data from the <router-link to="/positions" class="text-tv-blue hover:underline">Positions</router-link> page first.</p>
  </div>

  <!-- Main Content -->
  <main v-else class="p-4">

    <!-- Summary Cards -->
    <div class="grid grid-cols-6 gap-3 mb-4">
      <!-- Net Liquidating Value -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-blue">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Net Liquidating Value</div>
        <div class="text-2xl font-bold text-tv-text">
          ${{ formatNumber(currentBalance?.net_liquidating_value || 0) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          Cash: ${{ formatNumber(currentBalance?.cash_balance || 0) }}
        </div>
      </div>

      <!-- Daily Theta -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="portfolioTotals.netTheta >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#920;</span> Daily Theta
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netTheta >= 0 ? 'text-tv-green' : 'text-tv-red'">
          {{ portfolioTotals.netTheta >= 0 ? '+' : '' }}${{ formatNumber(Math.abs(portfolioTotals.netTheta)) }}<span class="text-sm font-normal text-tv-muted">/day</span>
        </div>
        <div class="text-xs mt-1" :class="portfolioTotals.netTheta >= 0 ? 'text-tv-green/70' : 'text-tv-red/70'">
          ${{ formatNumber(Math.abs(portfolioTotals.netTheta * 30)) }}/month projected
        </div>
      </div>

      <!-- Net Delta -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="portfolioTotals.netDelta >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#916;</span> Net Delta
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netDelta >= 0 ? 'text-tv-green' : 'text-tv-red'">
          {{ formatDelta(portfolioTotals.netDelta) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          ${{ formatNumber(Math.abs(portfolioTotals.deltaDollars)) }} delta-adjusted
        </div>
      </div>

      <!-- Net Gamma -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-amber">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#915;</span> Net Gamma
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netGamma >= 0 ? 'text-tv-amber' : 'text-tv-amber'">
          {{ formatDelta(portfolioTotals.netGamma) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          Delta change per $1 move
        </div>
      </div>

      <!-- Net Vega -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-purple">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#957;</span> Net Vega
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netVega >= 0 ? 'text-tv-purple' : 'text-tv-purple'">
          {{ portfolioTotals.netVega >= 0 ? '+' : '' }}${{ formatNumber(Math.abs(portfolioTotals.netVega)) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          P&amp;L per 1% IV change
        </div>
      </div>

      <!-- Buying Power Utilization -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="bpUtilization < 50 ? 'border-l-tv-green' : bpUtilization < 75 ? 'border-l-tv-amber' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">BP Utilization</div>
        <div class="text-2xl font-bold"
             :class="bpUtilization < 50 ? 'text-tv-green' : bpUtilization < 75 ? 'text-tv-amber' : 'text-tv-red'">
          {{ bpUtilization.toFixed(1) }}%
        </div>
        <div class="text-xs text-tv-muted mt-1">
          ${{ formatNumber(Math.abs((currentBalance?.net_liquidating_value || 0) - (currentBalance?.derivative_buying_power || 0))) }}
          / ${{ formatNumber(currentBalance?.net_liquidating_value || 0) }}
        </div>
      </div>
    </div>

    <!-- Charts Row 1 -->
    <div class="grid grid-cols-2 gap-3 mb-3">
      <!-- Delta Exposure -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-arrows-left-right mr-1 text-tv-blue"></i>Delta Exposure by Underlying
          <span class="text-xs font-normal ml-2">(delta dollars)</span>
        </div>
        <div id="chart-delta" style="min-height: 280px;"></div>
      </div>

      <!-- Theta Income Projection -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-chart-area mr-1 text-tv-green"></i>Theta Income Projection
          <span class="text-xs font-normal ml-2">(cumulative over 45 days)</span>
        </div>
        <div id="chart-theta" style="min-height: 280px;"></div>
      </div>
    </div>

    <!-- Charts Row 2 -->
    <div class="grid grid-cols-2 gap-3 mb-3">
      <!-- Portfolio Concentration Treemap -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-th-large mr-1 text-tv-cyan"></i>Portfolio Concentration
          <span class="text-xs font-normal ml-2">(sized by max risk, colored by P&amp;L)</span>
        </div>
        <div id="chart-treemap" style="min-height: 280px;"></div>
      </div>

      <!-- Market Scenario Analysis -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-flask mr-1 text-tv-amber"></i>Market Scenario Analysis
          <span class="text-xs font-normal ml-2">(P&amp;L at correlated market moves)</span>
        </div>
        <div id="chart-scenario" style="min-height: 280px;"></div>
      </div>
    </div>

    <!-- Risk Detail Table -->
    <div class="bg-tv-panel border border-tv-border">
      <div class="px-4 py-3 border-b border-tv-border flex items-center justify-between">
        <span class="text-sm text-tv-muted uppercase tracking-wider">
          <i class="fas fa-table mr-1 text-tv-blue"></i>Per-Underlying Risk Breakdown
        </span>
        <span class="text-xs text-tv-muted">
          Click column headers to sort
        </span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-tv-muted text-xs uppercase tracking-wider border-b border-tv-border">
              <th class="text-left px-4 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('underlying')">
                Underlying <span v-if="sortColumn === 'underlying'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('positionCount')">
                Pos <span v-if="sortColumn === 'positionCount'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('underlyingPrice')">
                Price <span v-if="sortColumn === 'underlyingPrice'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netDelta')">
                Delta <span v-if="sortColumn === 'netDelta'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('deltaDollars')">
                Delta $ <span v-if="sortColumn === 'deltaDollars'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netGamma')">
                Gamma <span v-if="sortColumn === 'netGamma'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netTheta')">
                Theta <span v-if="sortColumn === 'netTheta'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netVega')">
                Vega <span v-if="sortColumn === 'netVega'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('maxRisk')">
                Max Risk <span v-if="sortColumn === 'maxRisk'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('unrealizedPnl')">
                Unreal P&amp;L <span v-if="sortColumn === 'unrealizedPnl'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3">% Port</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="group in sortedGroups" :key="group.underlying"
                class="border-b border-tv-border/50 hover:bg-tv-border/20 transition-colors">
              <td class="px-4 py-3 font-semibold text-tv-text">{{ group.underlying }}</td>
              <td class="text-right px-3 py-3 text-tv-muted">{{ group.positionCount }}</td>
              <td class="text-right px-3 py-3 text-tv-text">${{ formatNumber(group.underlyingPrice) }}</td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.netDelta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ formatDelta(group.netDelta) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.deltaDollars >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (group.deltaDollars >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.deltaDollars)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-tv-amber">
                {{ formatDelta(group.netGamma) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.netTheta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (group.netTheta >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.netTheta)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-tv-purple">
                {{ (group.netVega >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.netVega)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-text">${{ formatNumber(group.maxRisk) }}</td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.unrealizedPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (group.unrealizedPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.unrealizedPnl)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-muted">
                {{ portfolioTotals.totalMaxRisk > 0 ? (group.maxRisk / portfolioTotals.totalMaxRisk * 100).toFixed(1) + '%' : '-' }}
              </td>
            </tr>
            <!-- Totals Row -->
            <tr class="border-t-2 border-tv-border bg-tv-bg/50 font-semibold">
              <td class="px-4 py-3 text-tv-text">PORTFOLIO</td>
              <td class="text-right px-3 py-3 text-tv-text">{{ portfolioTotals.positionCount }}</td>
              <td class="text-right px-3 py-3"></td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.netDelta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ formatDelta(portfolioTotals.netDelta) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.deltaDollars >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (portfolioTotals.deltaDollars >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.deltaDollars)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-tv-amber">
                {{ formatDelta(portfolioTotals.netGamma) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.netTheta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (portfolioTotals.netTheta >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.netTheta)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-tv-purple">
                {{ (portfolioTotals.netVega >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.netVega)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-text">${{ formatNumber(portfolioTotals.totalMaxRisk) }}</td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (portfolioTotals.totalPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.totalPnl)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-text">100%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Footer Note -->
    <div class="text-center text-xs text-tv-muted mt-4 pb-4">
      Greeks calculated via Black-Scholes model using underlying IV. Values are estimates and update with live quotes.
      Risk-free rate: 4.5%. Options multiplier: 100.
    </div>
  </main>
</template>

<style>
.greek-symbol {
  font-family: 'Times New Roman', Georgia, serif;
  font-style: italic;
  font-weight: bold;
}

/* ApexCharts tooltip overrides — hex must match design-tokens.js */
.apexcharts-tooltip { background: #1e222d !important; border: 1px solid #2a2e39 !important; color: #d1d4dc !important; } /* panel, border, text */
.apexcharts-tooltip-title { background: #131722 !important; border-bottom: 1px solid #2a2e39 !important; color: #d1d4dc !important; } /* bg, border, text */
.apexcharts-xaxistooltip, .apexcharts-yaxistooltip { background: #1e222d !important; border: 1px solid #2a2e39 !important; color: #d1d4dc !important; }
.apexcharts-xaxistooltip:after, .apexcharts-xaxistooltip:before { border-bottom-color: #2a2e39 !important; }

/* pulse-dot and metric-card are in main.css */
</style>
