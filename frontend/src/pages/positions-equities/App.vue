<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatDate } from '@/lib/formatters'
import StreamingPrice from '@/components/StreamingPrice.vue'
import PositionsToolbar from '@/components/PositionsToolbar.vue'

const Auth = useAuth()

// --- State ---
const allItems = ref([])
const accounts = ref([])
const underlyingQuotes = ref({})
const quoteUpdateCounter = ref(0)
const selectedAccount = ref('')
const selectedUnderlying = ref('')
const isLoading = ref(false)
const error = ref(null)
const liveQuotesActive = ref(false)
const lastQuoteUpdate = ref(null)
const syncSummary = ref(null)
const sortColumn = ref('underlying')
const sortDirection = ref('asc')
const expandedRows = ref({})

let ws = null

// --- Computed ---


const filteredItems = computed(() => {
  let items = allItems.value
  if (selectedAccount.value) {
    items = items.filter(i => i.accountNumber === selectedAccount.value)
  }
  if (selectedUnderlying.value) {
    items = items.filter(i => i.underlying === selectedUnderlying.value)
  }
  return items
})

const groupedPositions = computed(() => {
  // eslint-disable-next-line no-unused-vars
  const _ = quoteUpdateCounter.value

  const sorted = [...filteredItems.value]
  sorted.sort((a, b) => {
    let aVal, bVal
    switch (sortColumn.value) {
      case 'quantity':
        aVal = a.quantity || 0
        bVal = b.quantity || 0
        break
      case 'avg_price':
        aVal = a.avgPrice || 0
        bVal = b.avgPrice || 0
        break
      case 'cost_basis':
        aVal = a.costBasis || 0
        bVal = b.costBasis || 0
        break
      case 'market_value':
        aVal = getMarketValue(a)
        bVal = getMarketValue(b)
        break
      case 'pnl':
        aVal = getUnrealizedPnL(a)
        bVal = getUnrealizedPnL(b)
        break
      case 'pnl_percent':
        aVal = getPnLPercent(a)
        bVal = getPnLPercent(b)
        break
      case 'price':
        aVal = getQuotePrice(a.underlying) || 0
        bVal = getQuotePrice(b.underlying) || 0
        break
      default:
        aVal = (a.underlying || '').toLowerCase()
        bVal = (b.underlying || '').toLowerCase()
    }
    if (aVal < bVal) return sortDirection.value === 'asc' ? -1 : 1
    if (aVal > bVal) return sortDirection.value === 'asc' ? 1 : -1
    return 0
  })
  return sorted
})

const totalCostBasis = computed(() => {
  const _ = quoteUpdateCounter.value
  return filteredItems.value.reduce((s, i) => s + (i.costBasis || 0), 0)
})

const totalMarketValue = computed(() => {
  const _ = quoteUpdateCounter.value
  return filteredItems.value.reduce((s, i) => s + getMarketValue(i), 0)
})

const totalPnL = computed(() => {
  const _ = quoteUpdateCounter.value
  return filteredItems.value.reduce((s, i) => s + getUnrealizedPnL(i), 0)
})

// --- Methods ---

async function fetchAccounts() {
  try {
    const response = await Auth.authFetch('/api/accounts')
    const data = await response.json()
    accounts.value = (data.accounts || []).sort((a, b) => {
      const getOrder = (name) => {
        const n = (name || '').toUpperCase()
        if (n.includes('ROTH')) return 1
        if (n.includes('INDIVIDUAL')) return 2
        if (n.includes('TRADITIONAL')) return 3
        return 4
      }
      return getOrder(a.account_name) - getOrder(b.account_name)
    })
  } catch (err) { console.error('Failed to load accounts:', err) }
}

async function syncAndLoad() {
  isLoading.value = true
  error.value = null
  syncSummary.value = null
  try {
    const syncResp = await Auth.authFetch('/api/sync', { method: 'POST' })
    if (syncResp.ok) {
      const syncData = await syncResp.json()
      const n = syncData.new_transactions || 0
      const syms = syncData.symbols || []
      if (n > 0) {
        syncSummary.value = `Imported ${n} transaction${n === 1 ? '' : 's'} on ${syms.join(', ')}`
      } else {
        syncSummary.value = 'No new transactions'
      }
    }
  } catch (err) {
    console.error('Sync failed:', err)
  }
  await loadPositions()
}

async function loadPositions() {
  isLoading.value = true
  error.value = null
  try {
    const response = await Auth.authFetch('/api/open-chains')
    const data = await response.json()

    const items = []
    if (typeof data === 'object' && !Array.isArray(data)) {
      Object.entries(data).forEach(([accountNumber, accountData]) => {
        const chains = accountData.chains || []
        chains.forEach(chain => {
          const eqLegs = chain.equity_legs || []
          if (eqLegs.length === 0) return
          const eqSummary = chain.equity_summary || {}
          items.push({
            underlying: chain.underlying,
            accountNumber,
            groupId: chain.group_id,
            strategyType: chain.strategy_type || 'Shares',
            quantity: eqSummary.quantity || 0,
            avgPrice: eqSummary.average_price || 0,
            costBasis: eqSummary.cost_basis || 0,
            openingDate: chain.opening_date,
            hasOptions: (chain.open_legs || []).length > 0,
            optionStrategy: (chain.open_legs || []).length > 0 ? chain.strategy_type : null,
            equityLegs: eqLegs,
          })
        })
      })
    }
    allItems.value = items
  } catch (err) {
    console.error('Failed to load positions:', err)
    error.value = 'Failed to load positions'
  } finally {
    isLoading.value = false
  }
}

function getQuote(underlying) {
  return underlyingQuotes.value[underlying] || {}
}

function getQuotePrice(underlying) {
  return getQuote(underlying).price || null
}

function getMarketValue(item) {
  const price = getQuotePrice(item.underlying)
  if (!price) return 0
  return price * item.quantity
}

function getUnrealizedPnL(item) {
  const mv = getMarketValue(item)
  if (mv === 0) return 0
  return mv - item.costBasis
}

function getPnLPercent(item) {
  if (!item.costBasis || item.costBasis === 0) return 0
  return (getUnrealizedPnL(item) / Math.abs(item.costBasis)) * 100
}

function getAccountSymbol(accountNumber) {
  const account = accounts.value.find(a => a.account_number === accountNumber)
  if (!account) return '?'
  const name = (account.account_name || '').toUpperCase()
  if (name.includes('ROTH')) return 'R'
  if (name.includes('INDIVIDUAL')) return 'I'
  if (name.includes('TRADITIONAL')) return 'T'
  return name.charAt(0) || '?'
}

function getAccountBadgeClass(accountNumber) {
  const symbol = getAccountSymbol(accountNumber)
  if (symbol === 'R') return 'bg-tv-purple/20 text-tv-purple'
  if (symbol === 'I') return 'bg-tv-blue/20 text-tv-blue'
  if (symbol === 'T') return 'bg-tv-green/20 text-tv-green'
  return 'bg-tv-border text-tv-muted'
}

function toggleExpanded(groupId) {
  expandedRows.value = { ...expandedRows.value, [groupId]: !expandedRows.value[groupId] }
}

function getLotMarketValue(item, leg) {
  const price = getQuotePrice(item.underlying)
  if (!price) return 0
  const signed = leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity
  return price * signed
}

function getLotPnL(item, leg) {
  const mv = getLotMarketValue(item, leg)
  if (mv === 0) return 0
  return mv + (leg.cost_basis || 0)
}

function sort(column) {
  if (sortColumn.value === column) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = column
    if (['pnl', 'pnl_percent', 'market_value', 'cost_basis', 'price'].includes(column)) {
      sortDirection.value = 'desc'
    } else {
      sortDirection.value = 'asc'
    }
  }
}

function sortIcon(column) {
  if (sortColumn.value !== column) return ''
  return sortDirection.value === 'asc' ? '\u25B2' : '\u25BC'
}


// --- Quotes ---

function collectSymbols() {
  return [...new Set(filteredItems.value.map(i => i.underlying).filter(Boolean))]
}

async function loadCachedQuotes() {
  try {
    const symbols = collectSymbols()
    if (symbols.length === 0) return
    const response = await Auth.authFetch(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`)
    if (response.ok) {
      const quotes = await response.json()
      const updated = { ...underlyingQuotes.value }
      for (const [symbol, quoteData] of Object.entries(quotes)) {
        if (quoteData && typeof quoteData === 'object') {
          updated[symbol] = { ...updated[symbol], ...quoteData }
        }
      }
      underlyingQuotes.value = updated
      lastQuoteUpdate.value = new Date().toLocaleTimeString()
      quoteUpdateCounter.value++
    }
  } catch (err) { console.error('Error loading cached quotes:', err) }
}

async function initializeWebSocket() {
  try {
    const wsUrl = await Auth.getAuthenticatedWsUrl('/ws/quotes')
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      liveQuotesActive.value = true
      const symbols = collectSymbols()
      if (symbols.length > 0) {
        ws.send(JSON.stringify({ type: 'subscribe', symbols }))
      }
    }
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'quote' && msg.symbol) {
          underlyingQuotes.value = {
            ...underlyingQuotes.value,
            [msg.symbol]: { ...underlyingQuotes.value[msg.symbol], ...msg }
          }
          lastQuoteUpdate.value = new Date().toLocaleTimeString()
          quoteUpdateCounter.value++
        }
      } catch (e) {}
    }
    ws.onclose = () => { liveQuotesActive.value = false }
    ws.onerror = () => { liveQuotesActive.value = false }
  } catch (err) { console.error('WebSocket error:', err) }
}

function onAccountChange() {
  localStorage.setItem('trade_journal_selected_account', selectedAccount.value)
}

// --- Lifecycle ---

onMounted(async () => {
  const savedAccount = localStorage.getItem('trade_journal_selected_account')
  if (savedAccount) selectedAccount.value = savedAccount
  await fetchAccounts()
  await loadPositions()
  await loadCachedQuotes()
  await initializeWebSocket()
})

onUnmounted(() => {
  if (ws) { ws.close(); ws = null }
})
</script>

<template>
  <Teleport to="#nav-right">
    <select v-model="selectedAccount" @change="onAccountChange()"
            class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-1.5 rounded">
      <option value="">All Accounts</option>
      <option v-for="account in accounts" :key="account.account_number"
              :value="account.account_number">
        ({{ getAccountSymbol(account.account_number) }}) {{ account.account_name || account.account_number }}
      </option>
    </select>
  </Teleport>

  <!-- Sticky Header -->
  <div class="sticky top-14 z-30">
    <PositionsToolbar
      :is-loading="isLoading"
      :live-quotes-active="liveQuotesActive"
      :last-quote-update="lastQuoteUpdate"
      :sync-summary="syncSummary"
      :selected-account="selectedAccount"
      v-model:symbol-filter="selectedUnderlying"
      @sync="syncAndLoad()"
      @update:sync-summary="syncSummary = $event"
    />

    <!-- Stats Bar -->
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center gap-8 text-base">
      <span class="text-tv-muted">
        Positions: <span class="text-tv-text">{{ filteredItems.length }}</span>
      </span>
      <span class="text-tv-muted">
        Cost Basis: <span class="text-tv-text">${{ formatNumber(totalCostBasis) }}</span>
      </span>
      <span class="text-tv-muted">
        Market Value: <span class="text-tv-text">${{ formatNumber(totalMarketValue) }}</span>
      </span>
      <span class="text-tv-muted">
        Unrealized P&amp;L:
        <span :class="totalPnL >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(totalPnL) }}</span>
      </span>
    </div>

    <!-- Column Headers -->
    <div v-if="!isLoading && groupedPositions.length > 0"
         class="flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
      <span class="w-6 mr-2"></span>
      <span class="w-8 mr-3"></span>
      <span class="w-56 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sort('underlying')">
        Symbol <span v-if="sortIcon('underlying')" class="text-tv-blue">{{ sortIcon('underlying') }}</span>
      </span>
      <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sort('quantity')">
        Shares <span v-if="sortIcon('quantity')" class="text-tv-blue">{{ sortIcon('quantity') }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-4" @click="sort('avg_price')">
        Avg Price <span v-if="sortIcon('avg_price')" class="text-tv-blue">{{ sortIcon('avg_price') }}</span>
      </span>
      <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('cost_basis')">
        Cost Basis <span v-if="sortIcon('cost_basis')" class="text-tv-blue">{{ sortIcon('cost_basis') }}</span>
      </span>
      <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('market_value')">
        Mkt Value <span v-if="sortIcon('market_value')" class="text-tv-blue">{{ sortIcon('market_value') }}</span>
      </span>
      <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('pnl')">
        P&amp;L <span v-if="sortIcon('pnl')" class="text-tv-blue">{{ sortIcon('pnl') }}</span>
      </span>
      <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('pnl_percent')">
        P&amp;L % <span v-if="sortIcon('pnl_percent')" class="text-tv-blue">{{ sortIcon('pnl_percent') }}</span>
      </span>
    </div>
  </div>

  <!-- Loading State -->
  <div v-if="isLoading" class="text-center py-16">
    <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
    <p class="text-tv-muted">Loading equity positions...</p>
  </div>

  <!-- Empty State -->
  <div v-else-if="groupedPositions.length === 0" class="text-center py-16">
    <i class="fas fa-layer-group text-3xl text-tv-muted mb-3"></i>
    <p class="text-tv-muted">No equity positions found.</p>
  </div>

  <!-- Position List -->
  <div v-else class="bg-tv-panel border-x border-b border-tv-border">
    <div class="divide-y divide-tv-border">
      <div v-for="item in groupedPositions" :key="item.groupId">
        <!-- Summary row -->
        <div class="flex items-center px-4 h-12 hover:bg-tv-border/20 transition-colors"
             :class="item.equityLegs.length > 1 ? 'cursor-pointer' : ''"
             @click="item.equityLegs.length > 1 && toggleExpanded(item.groupId)">
          <!-- Chevron (only when multiple lots) -->
          <span class="w-6 mr-2">
            <i v-if="item.equityLegs.length > 1"
               class="fas fa-chevron-right text-tv-muted text-xs transition-transform duration-150"
               :class="{ 'rotate-90': expandedRows[item.groupId] }"></i>
          </span>

          <!-- Account badge -->
          <span class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mr-3"
                :class="getAccountBadgeClass(item.accountNumber)">
            {{ getAccountSymbol(item.accountNumber) }}
          </span>

          <!-- Symbol + Streaming Price -->
          <span class="w-56 flex items-center gap-3">
            <span class="text-lg font-semibold text-tv-text">{{ item.underlying }}</span>
            <span v-if="item.hasOptions" class="text-[10px] px-1.5 py-0.5 rounded bg-tv-blue/20 text-tv-blue border border-tv-blue/30">
              {{ item.optionStrategy }}
            </span>
            <span v-if="item.equityLegs.length > 1" class="text-[10px] text-tv-muted">
              {{ item.equityLegs.length }} lots
            </span>
            <span class="ml-auto">
              <StreamingPrice :quote="getQuote(item.underlying).price ? getQuote(item.underlying) : null" />
            </span>
          </span>

          <!-- Shares -->
          <span class="w-20 text-right text-base font-medium"
                :class="item.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
            {{ item.quantity }}
          </span>

          <!-- Avg Price -->
          <span class="w-24 text-right text-tv-muted text-base ml-4">
            ${{ formatNumber(item.avgPrice) }}
          </span>

          <!-- Cost Basis -->
          <span class="w-28 text-right text-tv-muted text-base ml-2">
            ${{ formatNumber(item.costBasis) }}
          </span>

          <!-- Market Value -->
          <span class="w-28 text-right text-base ml-2"
                :class="getMarketValue(item) ? 'text-tv-text' : 'text-tv-muted'">
            {{ getMarketValue(item) ? '$' + formatNumber(getMarketValue(item)) : '\u2014' }}
          </span>

          <!-- Unrealized P&L -->
          <span class="w-28 text-right text-base font-medium ml-2"
                :class="getUnrealizedPnL(item) > 0 ? 'text-tv-green' : getUnrealizedPnL(item) < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ getMarketValue(item) ? '$' + formatNumber(getUnrealizedPnL(item)) : '' }}
          </span>

          <!-- P&L % -->
          <span class="w-20 text-right text-base ml-2"
                :class="getPnLPercent(item) > 0 ? 'text-tv-green' : getPnLPercent(item) < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ getMarketValue(item) ? formatNumber(getPnLPercent(item)) + '%' : '' }}
          </span>
        </div>

        <!-- Expanded lots -->
        <div v-if="expandedRows[item.groupId] && item.equityLegs.length > 1"
             class="bg-tv-bg border-t border-tv-border/30">
          <div v-for="leg in item.equityLegs" :key="leg.lot_id"
               class="flex items-center px-4 py-1.5 text-sm hover:bg-tv-border/10">
            <span class="w-6 mr-2"></span>
            <span class="w-8 mr-3"></span>
            <span class="w-56 flex items-center gap-2">
              <span v-if="leg.derivation_type" class="text-[10px] px-1.5 py-0.5 rounded bg-tv-blue/15 text-tv-blue border border-tv-blue/20 uppercase">
                {{ leg.derivation_type }}
              </span>
              <span v-if="leg.entry_date" class="text-tv-muted text-xs">{{ formatDate(leg.entry_date) }}</span>
            </span>
            <span class="w-20 text-right font-medium"
                  :class="leg.quantity_direction === 'Long' ? 'text-tv-green' : 'text-tv-red'">
              {{ leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity }}
            </span>
            <span class="w-24 text-right text-tv-muted ml-4">${{ formatNumber(leg.entry_price) }}</span>
            <span class="w-28 text-right text-tv-muted ml-2">${{ formatNumber(Math.abs(leg.cost_basis)) }}</span>
            <span class="w-28 text-right ml-2"
                  :class="getLotMarketValue(item, leg) ? 'text-tv-text' : 'text-tv-muted'">
              {{ getLotMarketValue(item, leg) ? '$' + formatNumber(getLotMarketValue(item, leg)) : '\u2014' }}
            </span>
            <span class="w-28 text-right font-medium ml-2"
                  :class="getLotPnL(item, leg) > 0 ? 'text-tv-green' : getLotPnL(item, leg) < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ getLotMarketValue(item, leg) ? '$' + formatNumber(getLotPnL(item, leg)) : '' }}
            </span>
            <span class="w-20"></span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Bottom spacer -->
  <div class="h-96"></div>
</template>
