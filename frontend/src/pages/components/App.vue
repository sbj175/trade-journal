<script setup>
import { ref } from 'vue'

// --- Interactive state ---
const modalOpen = ref(false)
const toastVisible = ref(false)
const toastMessage = ref('')
const toggleOn = ref(true)
const toggleOff = ref(false)
const radioSelected = ref('monthly')
const checkboxChecked = ref(true)
const sampleSelect = ref('all')
const sampleText = ref('')
const sampleTextarea = ref('')
const sampleNumber = ref(-234.50)
const sampleDate = ref('2025-03-15')
const sampleColor = ref('#3b82f6')
const symbolFilter = ref('')
const tableExpanded = ref(false)
const tableSortCol = ref('symbol')
const tableSortDir = ref('asc')
const tableLoading = ref(false)
const tableEmpty = ref(false)

// Filter toggle states
const filterBullish = ref(true)
const filterBearish = ref(false)
const filterNeutral = ref(false)
const filterCredit = ref(true)
const filterDebit = ref(false)
const segmentActive = ref('positions')

// Loading button
const btnLoading = ref(false)

function showToast(msg) {
  toastMessage.value = msg
  toastVisible.value = true
  setTimeout(() => { toastVisible.value = false }, 3000)
}

function simulateLoading() {
  btnLoading.value = true
  setTimeout(() => { btnLoading.value = false }, 2000)
}

function simulateTableLoad() {
  tableLoading.value = true
  setTimeout(() => { tableLoading.value = false }, 1500)
}

// Mock table data
const tableData = [
  { symbol: 'SPY', strategy: 'Iron Condor', qty: 2, pnl: 342.00, status: 'OPEN' },
  { symbol: 'AAPL', strategy: 'Bull Put Spread', qty: 5, pnl: -128.50, status: 'CLOSED' },
  { symbol: 'TSLA', strategy: 'Cash Secured Put', qty: 1, pnl: 89.00, status: 'PARTIAL' },
  { symbol: 'QQQ', strategy: 'Bear Call Spread', qty: 3, pnl: 567.25, status: 'ASSIGNED' },
  { symbol: 'AMZN', strategy: 'Covered Call', qty: 1, pnl: -45.00, status: 'EXPIRED' },
]

// Financial data for font comparison
const fontSamples = [
  { label: 'Portfolio Value', value: '$128,432.57' },
  { label: 'Day P&L', value: '+$1,247.83' },
  { label: 'Open P&L', value: '-$3,891.20' },
  { label: 'Win Rate', value: '67.3%' },
  { label: 'Avg Return', value: '+2.41%' },
  { label: 'Max Drawdown', value: '-8.72%' },
]

const comparisonFonts = [
  'IBM Plex Mono',
  'JetBrains Mono',
  'Fira Code',
  'Space Mono',
  'DM Mono',
  'Inconsolata',
]

// Color tokens
const colorTokens = [
  { name: 'bg', hex: '#0b0f19', usage: 'Page background' },
  { name: 'panel', hex: '#141926', usage: 'Card / section backgrounds' },
  { name: 'border', hex: '#1e2536', usage: 'Borders, dividers' },
  { name: 'hover', hex: '#283148', usage: 'Hover states, active rows' },
  { name: 'text', hex: '#e6e9f0', usage: 'Primary text' },
  { name: 'muted', hex: '#6b7385', usage: 'Secondary text, labels' },
  { name: 'green', hex: '#00dc82', usage: 'Profit, positive, long' },
  { name: 'red', hex: '#ff4757', usage: 'Loss, negative, short' },
  { name: 'blue', hex: '#3b82f6', usage: 'Brand, interactive, links' },
  { name: 'amber', hex: '#f59e0b', usage: 'Warnings, DTE, gamma' },
  { name: 'orange', hex: '#f97316', usage: 'Assignments, severe warnings' },
  { name: 'cyan', hex: '#06b6d4', usage: 'Credit filter, info highlights' },
  { name: 'purple', hex: '#8b5cf6', usage: 'Vega, exercise, account badges' },
]

// Tag popover
const tagPopoverOpen = ref(false)
const tagSearch = ref('')
const sampleTags = ['Earnings Play', 'Hedge', 'Momentum', 'Theta Gang', 'LEAPS']
</script>

<template>
  <div class="max-w-6xl mx-auto px-6 py-8">

    <div class="mb-10">
      <h1 class="text-2xl font-bold text-tv-text mb-1">
        <i class="fas fa-swatchbook mr-2 text-tv-blue"></i>Component Library
      </h1>
      <p class="text-tv-muted text-sm">
        Every UI pattern used across OptionLedger — for evaluation, comparison, and experimentation.
      </p>
    </div>

    <!-- ================================================================
         1. TYPOGRAPHY & FONT COMPARISON
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">1</span>
        Typography & Font Comparison
      </h2>
      <p class="text-tv-muted text-sm mb-4">Plus Jakarta Sans for UI chrome, IBM Plex Mono for financial data.</p>

      <div class="grid grid-cols-2 gap-5 mb-6">
        <!-- Plus Jakarta Sans specimens -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Plus Jakarta Sans</div>
          <div class="space-y-2">
            <div class="text-2xl font-bold text-tv-text">Heading 2XL Bold</div>
            <div class="text-xl font-semibold text-tv-text">Heading XL Semibold</div>
            <div class="text-lg font-semibold text-tv-text">Heading LG Semibold</div>
            <div class="text-base font-medium text-tv-text">Body Base Medium</div>
            <div class="text-sm text-tv-text">Body SM Regular</div>
            <div class="text-xs text-tv-muted">Body XS Muted</div>
            <div class="text-xs uppercase tracking-wider text-tv-muted font-medium">UPPERCASE LABEL</div>
          </div>
        </div>

        <!-- IBM Plex Mono specimens -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">IBM Plex Mono</div>
          <div class="space-y-2 font-mono">
            <div class="text-2xl font-semibold text-tv-green">$128,432.57</div>
            <div class="text-xl font-medium text-tv-red">-$3,891.20</div>
            <div class="text-lg text-tv-text">+2.41%</div>
            <div class="text-base text-tv-text">67.3% win rate</div>
            <div class="text-sm text-tv-muted">0.32 delta | -0.04 theta</div>
            <div class="text-xs text-tv-muted">SPY 250321P550</div>
          </div>
        </div>
      </div>

      <!-- Font Shootout -->
      <div class="bg-tv-panel border border-tv-border rounded p-5">
        <div class="text-xs uppercase tracking-wider text-tv-muted mb-4 font-medium">Font Comparison — Financial Data</div>
        <div class="grid grid-cols-3 gap-4">
          <div v-for="font in comparisonFonts" :key="font" class="border border-tv-border rounded p-3">
            <div class="text-xs text-tv-muted mb-2 font-medium">{{ font }}</div>
            <div class="space-y-1" :style="{ fontFamily: `'${font}', monospace`, fontVariantNumeric: 'tabular-nums' }">
              <div v-for="s in fontSamples" :key="s.label" class="flex justify-between text-sm">
                <span class="text-tv-muted">{{ s.label }}</span>
                <span :class="s.value.startsWith('+') ? 'text-tv-green' : s.value.startsWith('-') ? 'text-tv-red' : 'text-tv-text'">{{ s.value }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         2. COLOR PALETTE
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">2</span>
        Color Palette
      </h2>
      <p class="text-tv-muted text-sm mb-4">All 13 design tokens with semantic usage.</p>

      <div class="grid grid-cols-4 gap-3">
        <div v-for="c in colorTokens" :key="c.name"
             class="bg-tv-panel border border-tv-border rounded p-3 flex items-start gap-3">
          <div class="w-10 h-10 rounded border border-tv-border shrink-0" :style="{ backgroundColor: c.hex }"></div>
          <div class="min-w-0">
            <div class="text-sm font-medium text-tv-text">{{ c.name }}</div>
            <div class="text-xs font-mono text-tv-muted">{{ c.hex }}</div>
            <div class="text-xs text-tv-muted mt-0.5">{{ c.usage }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         3. BUTTONS
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">3</span>
        Buttons
      </h2>
      <p class="text-tv-muted text-sm mb-4">All button variants used across the app.</p>

      <div class="space-y-5">
        <!-- Primary / Success / Danger -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Solid Buttons</div>
          <div class="flex items-center gap-3 flex-wrap">
            <button class="px-4 py-2 bg-tv-blue text-white text-sm font-medium rounded hover:bg-tv-blue/80 transition-colors">
              <i class="fas fa-plus mr-1.5"></i>Primary
            </button>
            <button class="px-4 py-2 bg-tv-green text-white text-sm font-medium rounded hover:bg-tv-green/80 transition-colors"
                    @click="showToast('Sync complete — 42 transactions imported')">
              <i class="fas fa-sync mr-1.5"></i>Sync Trades
            </button>
            <button class="px-4 py-2 bg-tv-red text-white text-sm font-medium rounded hover:bg-tv-red/80 transition-colors">
              <i class="fas fa-trash mr-1.5"></i>Delete
            </button>
          </div>
        </div>

        <!-- Secondary / Outline / Ghost -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Secondary / Outline / Ghost</div>
          <div class="flex items-center gap-3 flex-wrap">
            <button class="px-4 py-2 bg-tv-border text-tv-text text-sm font-medium rounded hover:bg-tv-hover transition-colors">
              Secondary
            </button>
            <button class="px-4 py-2 border border-tv-border text-tv-text text-sm font-medium rounded hover:bg-tv-hover transition-colors">
              Outline
            </button>
            <button class="px-3 py-2 text-tv-muted text-sm font-medium rounded hover:text-tv-text hover:bg-tv-border/50 transition-colors">
              Ghost
            </button>
          </div>
        </div>

        <!-- Filter toggles -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Filter Toggles</div>
          <div class="flex items-center gap-2 flex-wrap">
            <button @click="filterBullish = !filterBullish"
                    :class="filterBullish ? 'bg-tv-green/15 text-tv-green border-tv-green/30' : 'bg-transparent text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-xs font-medium rounded border transition-colors">
              Bullish
            </button>
            <button @click="filterBearish = !filterBearish"
                    :class="filterBearish ? 'bg-tv-red/15 text-tv-red border-tv-red/30' : 'bg-transparent text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-xs font-medium rounded border transition-colors">
              Bearish
            </button>
            <button @click="filterNeutral = !filterNeutral"
                    :class="filterNeutral ? 'bg-tv-amber/15 text-tv-amber border-tv-amber/30' : 'bg-transparent text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-xs font-medium rounded border transition-colors">
              Neutral
            </button>
            <span class="w-px h-5 bg-tv-border mx-1"></span>
            <button @click="filterCredit = !filterCredit"
                    :class="filterCredit ? 'bg-tv-cyan/15 text-tv-cyan border-tv-cyan/30' : 'bg-transparent text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-xs font-medium rounded border transition-colors">
              Credit
            </button>
            <button @click="filterDebit = !filterDebit"
                    :class="filterDebit ? 'bg-tv-purple/15 text-tv-purple border-tv-purple/30' : 'bg-transparent text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-xs font-medium rounded border transition-colors">
              Debit
            </button>
          </div>
        </div>

        <!-- Segmented control -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Segmented Control</div>
          <div class="inline-flex bg-tv-bg rounded border border-tv-border">
            <button @click="segmentActive = 'positions'"
                    :class="segmentActive === 'positions' ? 'bg-tv-blue text-white' : 'text-tv-muted hover:text-tv-text'"
                    class="px-4 py-1.5 text-sm font-medium rounded transition-colors">
              Positions
            </button>
            <button @click="segmentActive = 'orders'"
                    :class="segmentActive === 'orders' ? 'bg-tv-blue text-white' : 'text-tv-muted hover:text-tv-text'"
                    class="px-4 py-1.5 text-sm font-medium rounded transition-colors">
              Orders
            </button>
          </div>
        </div>

        <!-- Icon-only / Loading / Disabled -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Icon-Only / Loading / Disabled</div>
          <div class="flex items-center gap-3 flex-wrap">
            <button class="w-8 h-8 flex items-center justify-center rounded text-tv-muted hover:text-tv-text hover:bg-tv-border/50 transition-colors">
              <i class="fas fa-chevron-down text-xs"></i>
            </button>
            <button class="w-8 h-8 flex items-center justify-center rounded text-tv-muted hover:text-tv-red hover:bg-tv-red/10 transition-colors">
              <i class="fas fa-trash text-xs"></i>
            </button>
            <button class="w-8 h-8 flex items-center justify-center rounded text-tv-muted hover:text-tv-text hover:bg-tv-border/50 transition-colors">
              <i class="fas fa-cog text-sm"></i>
            </button>
            <button class="w-8 h-8 flex items-center justify-center rounded text-tv-muted hover:text-tv-text hover:bg-tv-border/50 transition-colors">
              <i class="fas fa-xmark text-sm"></i>
            </button>
            <span class="w-px h-5 bg-tv-border mx-1"></span>
            <button @click="simulateLoading"
                    :disabled="btnLoading"
                    class="px-4 py-2 bg-tv-blue text-white text-sm font-medium rounded hover:bg-tv-blue/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
              <i v-if="btnLoading" class="fas fa-spinner fa-spin mr-1.5"></i>
              <i v-else class="fas fa-download mr-1.5"></i>
              {{ btnLoading ? 'Loading...' : 'Click to Load' }}
            </button>
            <button disabled class="px-4 py-2 bg-tv-border text-tv-muted text-sm font-medium rounded opacity-50 cursor-not-allowed">
              Disabled
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         4. FORM CONTROLS
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">4</span>
        Form Controls
      </h2>
      <p class="text-tv-muted text-sm mb-4">Inputs, selects, toggles, and other form elements.</p>

      <div class="grid grid-cols-2 gap-5">
        <!-- Select -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Select Dropdown</div>
          <select v-model="sampleSelect"
                  class="w-full bg-tv-bg border border-tv-border rounded px-3 py-2 text-sm text-tv-text">
            <option value="all">All Accounts</option>
            <option value="roth">Roth IRA</option>
            <option value="individual">Individual</option>
            <option value="trust">Trust</option>
          </select>
        </div>

        <!-- Text input with clear -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Symbol Filter (with clear)</div>
          <div class="relative">
            <i class="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-tv-muted text-xs"></i>
            <input v-model="symbolFilter" type="text" placeholder="Filter symbols..."
                   class="w-full bg-tv-bg border border-tv-border rounded pl-8 pr-8 py-2 text-sm text-tv-text placeholder:text-tv-muted/50">
            <button v-if="symbolFilter" @click="symbolFilter = ''"
                    class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text">
              <i class="fas fa-xmark text-xs"></i>
            </button>
          </div>
        </div>

        <!-- Text input -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Text Input</div>
          <input v-model="sampleText" type="text" placeholder="Enter text..."
                 class="w-full bg-tv-bg border border-tv-border rounded px-3 py-2 text-sm text-tv-text placeholder:text-tv-muted/50">
        </div>

        <!-- Textarea -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Textarea (Notes)</div>
          <textarea v-model="sampleTextarea" rows="3" placeholder="Add notes..."
                    class="w-full bg-tv-bg border border-tv-border rounded px-3 py-2 text-sm text-tv-text placeholder:text-tv-muted/50 resize-none"></textarea>
        </div>

        <!-- Number input -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Number Input (P&L colored)</div>
          <input v-model.number="sampleNumber" type="number" step="0.01"
                 :class="sampleNumber >= 0 ? 'text-tv-green' : 'text-tv-red'"
                 class="w-full bg-tv-bg border border-tv-border rounded px-3 py-2 text-sm font-mono">
        </div>

        <!-- Date input -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Date Input</div>
          <input v-model="sampleDate" type="date"
                 class="w-full bg-tv-bg border border-tv-border rounded px-3 py-2 text-sm text-tv-text">
        </div>

        <!-- Checkbox -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Checkbox</div>
          <div class="space-y-2">
            <label class="flex items-center gap-2.5 cursor-pointer">
              <input type="checkbox" v-model="checkboxChecked"
                     class="w-4 h-4 rounded border-tv-border bg-tv-bg accent-tv-blue">
              <span class="text-sm text-tv-text">Enable profit target alerts</span>
            </label>
            <label class="flex items-center gap-2.5 cursor-pointer">
              <input type="checkbox" checked disabled
                     class="w-4 h-4 rounded border-tv-border bg-tv-bg accent-tv-blue opacity-50">
              <span class="text-sm text-tv-muted">Always enabled (disabled)</span>
            </label>
          </div>
        </div>

        <!-- Toggle switch -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Toggle Switch</div>
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <span class="text-sm text-tv-text">Roll alerts</span>
              <button @click="toggleOn = !toggleOn"
                      :class="toggleOn ? 'bg-tv-blue' : 'bg-tv-border'"
                      class="relative w-10 h-5 rounded-full transition-colors">
                <span :class="toggleOn ? 'translate-x-5' : 'translate-x-0.5'"
                      class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"></span>
              </button>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-sm text-tv-text">Privacy mode</span>
              <button @click="toggleOff = !toggleOff"
                      :class="toggleOff ? 'bg-tv-blue' : 'bg-tv-border'"
                      class="relative w-10 h-5 rounded-full transition-colors">
                <span :class="toggleOff ? 'translate-x-5' : 'translate-x-0.5'"
                      class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"></span>
              </button>
            </div>
          </div>
        </div>

        <!-- Radio card group -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Radio Card Group</div>
          <div class="grid grid-cols-3 gap-2">
            <button v-for="opt in ['weekly', 'monthly', 'yearly']" :key="opt"
                    @click="radioSelected = opt"
                    :class="radioSelected === opt
                      ? 'border-tv-blue bg-tv-blue/10 text-tv-text'
                      : 'border-tv-border text-tv-muted hover:border-tv-hover hover:text-tv-text'"
                    class="px-3 py-2 rounded border text-sm font-medium transition-colors capitalize text-center">
              {{ opt }}
            </button>
          </div>
        </div>

        <!-- Color picker -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Color Picker</div>
          <div class="flex items-center gap-3">
            <input v-model="sampleColor" type="color"
                   class="w-10 h-10 rounded border border-tv-border cursor-pointer bg-transparent">
            <span class="text-sm font-mono text-tv-muted">{{ sampleColor }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         5. BADGES & PILLS
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">5</span>
        Badges & Pills
      </h2>
      <p class="text-tv-muted text-sm mb-4">Status indicators, account circles, tags, and mini-badges.</p>

      <div class="space-y-5">
        <!-- Status badges -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Status Badges</div>
          <div class="flex items-center gap-3 flex-wrap">
            <span class="px-2 py-0.5 text-xs font-medium rounded bg-tv-green/15 text-tv-green">OPEN</span>
            <span class="px-2 py-0.5 text-xs font-medium rounded bg-tv-border text-tv-muted">CLOSED</span>
            <span class="px-2 py-0.5 text-xs font-medium rounded bg-tv-amber/15 text-tv-amber">PARTIAL</span>
            <span class="px-2 py-0.5 text-xs font-medium rounded bg-tv-orange/15 text-tv-orange">ASSIGNED</span>
            <span class="px-2 py-0.5 text-xs font-medium rounded bg-tv-red/15 text-tv-red">EXPIRED</span>
          </div>
        </div>

        <!-- Account circles -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Account Circles</div>
          <div class="flex items-center gap-3">
            <span class="w-7 h-7 rounded-full bg-tv-purple/15 text-tv-purple text-xs font-bold flex items-center justify-center">R</span>
            <span class="w-7 h-7 rounded-full bg-tv-blue/15 text-tv-blue text-xs font-bold flex items-center justify-center">I</span>
            <span class="w-7 h-7 rounded-full bg-tv-green/15 text-tv-green text-xs font-bold flex items-center justify-center">T</span>
          </div>
        </div>

        <!-- Tag chips -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Tag Chips (removable)</div>
          <div class="flex items-center gap-2 flex-wrap">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-tv-blue/15 text-tv-blue border border-tv-blue/20">
              Earnings Play
              <button class="hover:text-white transition-colors"><i class="fas fa-xmark text-[10px]"></i></button>
            </span>
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-tv-green/15 text-tv-green border border-tv-green/20">
              Theta Gang
              <button class="hover:text-white transition-colors"><i class="fas fa-xmark text-[10px]"></i></button>
            </span>
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-tv-amber/15 text-tv-amber border border-tv-amber/20">
              Hedge
              <button class="hover:text-white transition-colors"><i class="fas fa-xmark text-[10px]"></i></button>
            </span>
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-tv-purple/15 text-tv-purple border border-tv-purple/20">
              LEAPS
              <button class="hover:text-white transition-colors"><i class="fas fa-xmark text-[10px]"></i></button>
            </span>
          </div>
        </div>

        <!-- Roll analysis mini-badges + count badge -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Roll Analysis & Count Badges</div>
          <div class="flex items-center gap-3 flex-wrap">
            <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-tv-green/15 text-tv-green">+$142</span>
            <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-tv-red/15 text-tv-red">-$89</span>
            <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-tv-amber/15 text-tv-amber">LATE</span>
            <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-tv-orange/15 text-tv-orange">HIGH Δ</span>
            <span class="w-px h-4 bg-tv-border"></span>
            <span class="px-2 py-0.5 text-xs font-medium rounded-full bg-tv-border text-tv-muted">12</span>
            <span class="px-2 py-0.5 text-xs font-medium rounded-full bg-tv-blue/15 text-tv-blue">3 new</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         6. CARDS
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">6</span>
        Cards
      </h2>
      <p class="text-tv-muted text-sm mb-4">Metric cards, settings panels, alerts, and onboarding.</p>

      <div class="space-y-5">
        <!-- Metric cards -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Metric Cards (border-l accent)</div>
          <div class="grid grid-cols-4 gap-3">
            <div class="metric-card bg-tv-bg border border-tv-border border-l-2 border-l-tv-green rounded p-4">
              <div class="text-xs text-tv-muted mb-1">Total P&L</div>
              <div class="text-xl font-mono font-semibold text-tv-green">+$4,231.50</div>
            </div>
            <div class="metric-card bg-tv-bg border border-tv-border border-l-2 border-l-tv-red rounded p-4">
              <div class="text-xs text-tv-muted mb-1">Open Risk</div>
              <div class="text-xl font-mono font-semibold text-tv-red">-$12,800</div>
            </div>
            <div class="metric-card bg-tv-bg border border-tv-border border-l-2 border-l-tv-blue rounded p-4">
              <div class="text-xs text-tv-muted mb-1">Win Rate</div>
              <div class="text-xl font-mono font-semibold text-tv-text">67.3%</div>
            </div>
            <div class="metric-card bg-tv-bg border border-tv-border border-l-2 border-l-tv-amber rounded p-4">
              <div class="text-xs text-tv-muted mb-1">Avg DTE</div>
              <div class="text-xl font-mono font-semibold text-tv-text">34</div>
            </div>
          </div>
        </div>

        <!-- Settings panel card -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Settings Panel Card</div>
          <div class="bg-tv-bg border border-tv-border rounded max-w-md">
            <div class="px-5 py-4 border-b border-tv-border">
              <h3 class="text-sm font-semibold text-tv-text">
                <i class="fas fa-bell mr-2 text-tv-blue"></i>Notification Preferences
              </h3>
            </div>
            <div class="p-5 text-sm text-tv-text space-y-3">
              <div class="flex items-center justify-between">
                <span>Email alerts</span>
                <span class="text-tv-green text-xs font-medium">Enabled</span>
              </div>
              <div class="flex items-center justify-between">
                <span>DTE warnings</span>
                <span class="text-tv-muted text-xs font-medium">21 days</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Alert cards -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Alert Cards</div>
          <div class="space-y-3 max-w-lg">
            <div class="flex items-start gap-3 p-3 rounded border border-tv-blue/20 bg-tv-blue/5">
              <i class="fas fa-info-circle text-tv-blue mt-0.5"></i>
              <div class="text-sm text-tv-text">
                <span class="font-medium">Info:</span> Market data updates every 30 seconds during market hours.
              </div>
            </div>
            <div class="flex items-start gap-3 p-3 rounded border border-tv-amber/20 bg-tv-amber/5">
              <i class="fas fa-exclamation-triangle text-tv-amber mt-0.5"></i>
              <div class="text-sm text-tv-text">
                <span class="font-medium">Warning:</span> 3 positions expire within 7 days.
              </div>
            </div>
            <div class="flex items-start gap-3 p-3 rounded border border-tv-red/20 bg-tv-red/5">
              <i class="fas fa-circle-xmark text-tv-red mt-0.5"></i>
              <div class="text-sm text-tv-text">
                <span class="font-medium">Error:</span> Failed to connect to Tastytrade API. Check your credentials.
              </div>
            </div>
          </div>
        </div>

        <!-- Onboarding / Welcome card -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Onboarding Card</div>
          <div class="bg-tv-blue/5 border border-tv-blue/20 rounded p-5 max-w-lg">
            <div class="flex items-start gap-4">
              <span class="w-10 h-10 rounded-lg bg-tv-blue/10 border border-tv-blue/25 flex items-center justify-center shrink-0">
                <i class="fas fa-rocket text-tv-blue"></i>
              </span>
              <div>
                <h3 class="text-sm font-semibold text-tv-text mb-1">Welcome to OptionLedger</h3>
                <p class="text-sm text-tv-muted mb-3">Connect your Tastytrade account to import your trades and start tracking performance.</p>
                <button class="px-4 py-2 bg-tv-blue text-white text-sm font-medium rounded hover:bg-tv-blue/80 transition-colors">
                  <i class="fas fa-link mr-1.5"></i>Connect Account
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         7. TABLE
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">7</span>
        Table
      </h2>
      <p class="text-tv-muted text-sm mb-4">Data table with sort indicators, expanded rows, subtotals, empty & loading states.</p>

      <div class="space-y-5">
        <!-- Controls -->
        <div class="flex items-center gap-3">
          <button @click="simulateTableLoad" class="px-3 py-1.5 text-xs font-medium rounded border border-tv-border text-tv-muted hover:text-tv-text transition-colors">
            <i class="fas fa-spinner mr-1"></i>Simulate Loading
          </button>
          <button @click="tableEmpty = !tableEmpty" class="px-3 py-1.5 text-xs font-medium rounded border border-tv-border text-tv-muted hover:text-tv-text transition-colors">
            {{ tableEmpty ? 'Show Data' : 'Show Empty' }}
          </button>
        </div>

        <!-- Table card -->
        <div class="bg-tv-panel border border-tv-border rounded overflow-hidden">
          <!-- Loading overlay -->
          <div v-if="tableLoading" class="flex items-center justify-center py-16">
            <div class="flex items-center gap-3">
              <div class="spinner" style="width: 24px; height: 24px; border-width: 2.5px;"></div>
              <span class="text-sm text-tv-muted">Loading positions...</span>
            </div>
          </div>

          <!-- Empty state -->
          <div v-else-if="tableEmpty" class="flex flex-col items-center justify-center py-16">
            <i class="fas fa-inbox text-tv-border text-3xl mb-3"></i>
            <p class="text-sm text-tv-muted mb-1">No positions found</p>
            <a href="#" class="text-xs text-tv-blue hover:underline">Sync trades to get started</a>
          </div>

          <!-- Data table -->
          <table v-else class="w-full text-sm">
            <thead>
              <tr class="border-b border-tv-border">
                <th class="text-left px-4 py-3 text-xs uppercase tracking-wider text-tv-muted font-medium cursor-pointer hover:text-tv-text transition-colors"
                    @click="tableSortCol = 'symbol'; tableSortDir = tableSortDir === 'asc' ? 'desc' : 'asc'">
                  Symbol
                  <i v-if="tableSortCol === 'symbol'" :class="tableSortDir === 'asc' ? 'fa-sort-up' : 'fa-sort-down'" class="fas ml-1 text-tv-blue"></i>
                </th>
                <th class="text-left px-4 py-3 text-xs uppercase tracking-wider text-tv-muted font-medium">Strategy</th>
                <th class="text-right px-4 py-3 text-xs uppercase tracking-wider text-tv-muted font-medium">Qty</th>
                <th class="text-right px-4 py-3 text-xs uppercase tracking-wider text-tv-muted font-medium cursor-pointer hover:text-tv-text transition-colors"
                    @click="tableSortCol = 'pnl'; tableSortDir = tableSortDir === 'asc' ? 'desc' : 'asc'">
                  P&L
                  <i v-if="tableSortCol === 'pnl'" :class="tableSortDir === 'asc' ? 'fa-sort-up' : 'fa-sort-down'" class="fas ml-1 text-tv-blue"></i>
                </th>
                <th class="text-center px-4 py-3 text-xs uppercase tracking-wider text-tv-muted font-medium">Status</th>
                <th class="w-10"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="(row, i) in tableData" :key="row.symbol">
                <tr class="border-b border-tv-border h-12 hover:bg-tv-hover/50 transition-colors cursor-pointer"
                    @click="tableExpanded = tableExpanded === i ? null : i">
                  <td class="px-4 font-medium text-tv-text">{{ row.symbol }}</td>
                  <td class="px-4 text-tv-muted">{{ row.strategy }}</td>
                  <td class="px-4 text-right font-mono text-tv-text">{{ row.qty }}</td>
                  <td class="px-4 text-right font-mono" :class="row.pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                    {{ row.pnl >= 0 ? '+' : '' }}${{ row.pnl.toFixed(2) }}
                  </td>
                  <td class="px-4 text-center">
                    <span :class="{
                      'bg-tv-green/15 text-tv-green': row.status === 'OPEN',
                      'bg-tv-border text-tv-muted': row.status === 'CLOSED',
                      'bg-tv-amber/15 text-tv-amber': row.status === 'PARTIAL',
                      'bg-tv-orange/15 text-tv-orange': row.status === 'ASSIGNED',
                      'bg-tv-red/15 text-tv-red': row.status === 'EXPIRED',
                    }" class="px-2 py-0.5 text-xs font-medium rounded">{{ row.status }}</span>
                  </td>
                  <td class="px-2">
                    <i :class="tableExpanded === i ? 'fa-chevron-up' : 'fa-chevron-down'" class="fas text-xs text-tv-muted"></i>
                  </td>
                </tr>
                <!-- Expanded detail -->
                <tr v-if="tableExpanded === i" class="bg-tv-bg border-b border-tv-border">
                  <td colspan="6" class="px-4 py-3">
                    <div class="text-xs text-tv-muted space-y-1 ml-1">
                      <div><span class="text-tv-text font-medium">Opened:</span> Jan 15, 2025</div>
                      <div><span class="text-tv-text font-medium">Expiration:</span> Mar 21, 2025</div>
                      <div><span class="text-tv-text font-medium">DTE:</span> <span class="text-tv-amber font-medium">17</span></div>
                    </div>
                  </td>
                </tr>
              </template>
              <!-- Subtotal row -->
              <tr class="bg-tv-blue/10 border-l-2 border-l-tv-blue font-medium">
                <td class="px-4 py-3 text-tv-text">Total</td>
                <td></td>
                <td class="px-4 text-right font-mono text-tv-text">12</td>
                <td class="px-4 text-right font-mono text-tv-green">+$824.75</td>
                <td></td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- ================================================================
         8. MODALS & OVERLAYS
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">8</span>
        Modals & Overlays
      </h2>
      <p class="text-tv-muted text-sm mb-4">Modal dialogs, popovers, and toast notifications.</p>

      <div class="space-y-5">
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Triggers</div>
          <div class="flex items-center gap-3">
            <button @click="modalOpen = true"
                    class="px-4 py-2 bg-tv-blue text-white text-sm font-medium rounded hover:bg-tv-blue/80 transition-colors">
              <i class="fas fa-expand mr-1.5"></i>Open Modal
            </button>
            <div class="relative">
              <button @click="tagPopoverOpen = !tagPopoverOpen"
                      class="px-4 py-2 border border-tv-border text-tv-text text-sm font-medium rounded hover:bg-tv-hover transition-colors">
                <i class="fas fa-tag mr-1.5"></i>Tag Popover
              </button>
              <!-- Tag popover dropdown -->
              <div v-if="tagPopoverOpen"
                   class="absolute top-full left-0 mt-1 w-56 bg-tv-panel border border-tv-border rounded shadow-lg z-10">
                <div class="p-2">
                  <input v-model="tagSearch" type="text" placeholder="Search tags..."
                         class="w-full bg-tv-bg border border-tv-border rounded px-2.5 py-1.5 text-xs text-tv-text placeholder:text-tv-muted/50">
                </div>
                <div class="border-t border-tv-border max-h-32 overflow-y-auto">
                  <button v-for="tag in sampleTags.filter(t => t.toLowerCase().includes(tagSearch.toLowerCase()))"
                          :key="tag"
                          @click="tagPopoverOpen = false; tagSearch = ''"
                          class="w-full text-left px-3 py-1.5 text-sm text-tv-text hover:bg-tv-hover transition-colors">
                    {{ tag }}
                  </button>
                </div>
              </div>
            </div>
            <button @click="showToast('Position note saved successfully')"
                    class="px-4 py-2 bg-tv-green text-white text-sm font-medium rounded hover:bg-tv-green/80 transition-colors">
              <i class="fas fa-check mr-1.5"></i>Show Toast
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- ================================================================
         9. LOADING & EMPTY STATES
         ================================================================ -->
    <section class="mb-12">
      <h2 class="text-lg font-semibold text-tv-text mb-1 flex items-center gap-2">
        <span class="w-6 h-6 rounded bg-tv-blue/10 flex items-center justify-center text-xs text-tv-blue font-bold">9</span>
        Loading & Empty States
      </h2>
      <p class="text-tv-muted text-sm mb-4">Spinners, pulse dots, and empty state patterns.</p>

      <div class="space-y-5">
        <!-- Spinners -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Spinners</div>
          <div class="flex items-center gap-6">
            <div class="flex items-center gap-2">
              <div class="spinner" style="width: 16px; height: 16px;"></div>
              <span class="text-xs text-tv-muted">16px (inline)</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="spinner" style="width: 32px; height: 32px; border-width: 2.5px;"></div>
              <span class="text-xs text-tv-muted">32px (standard)</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="spinner" style="width: 48px; height: 48px; border-width: 3px;"></div>
              <span class="text-xs text-tv-muted">48px (large)</span>
            </div>
          </div>
        </div>

        <!-- Empty states -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Empty States</div>
          <div class="grid grid-cols-2 gap-4">
            <div class="bg-tv-bg border border-tv-border rounded py-10 flex flex-col items-center justify-center">
              <i class="fas fa-chart-bar text-tv-border text-2xl mb-2"></i>
              <p class="text-sm text-tv-muted mb-1">No reports available</p>
              <a href="#" class="text-xs text-tv-blue hover:underline">Import trades to generate reports</a>
            </div>
            <div class="bg-tv-bg border border-tv-border rounded py-10 flex flex-col items-center justify-center">
              <i class="fas fa-search text-tv-border text-2xl mb-2"></i>
              <p class="text-sm text-tv-muted">No results match your filters</p>
            </div>
          </div>
        </div>

        <!-- Pulse dots -->
        <div class="bg-tv-panel border border-tv-border rounded p-5">
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-medium">Pulse Dots</div>
          <div class="flex items-center gap-6">
            <div class="flex items-center gap-2">
              <span class="pulse-dot bg-tv-green"></span>
              <span class="text-xs text-tv-text">Live</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="pulse-dot bg-tv-red"></span>
              <span class="text-xs text-tv-text">Offline</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="pulse-dot bg-tv-amber"></span>
              <span class="text-xs text-tv-text">Connecting</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <div class="text-center text-tv-muted text-xs pb-8">
      Component Library — dev/design tool only, not linked from main nav.
    </div>
  </div>

  <!-- ================================================================
       MODAL OVERLAY
       ================================================================ -->
  <Teleport to="body">
    <div v-if="modalOpen" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/60" @click="modalOpen = false"></div>
      <div class="relative bg-tv-panel border border-tv-border rounded-lg shadow-xl w-full max-w-md mx-4">
        <div class="flex items-center justify-between px-5 py-4 border-b border-tv-border">
          <h3 class="text-sm font-semibold text-tv-text">
            <i class="fas fa-exclamation-triangle text-tv-amber mr-2"></i>Confirm Action
          </h3>
          <button @click="modalOpen = false" class="text-tv-muted hover:text-tv-text transition-colors">
            <i class="fas fa-xmark"></i>
          </button>
        </div>
        <div class="p-5 text-sm text-tv-text">
          <p class="mb-4">Are you sure you want to close all positions for <span class="font-medium text-tv-text">SPY</span>? This action cannot be undone.</p>
          <div class="flex justify-end gap-3">
            <button @click="modalOpen = false"
                    class="px-4 py-2 border border-tv-border text-tv-text text-sm font-medium rounded hover:bg-tv-hover transition-colors">
              Cancel
            </button>
            <button @click="modalOpen = false; showToast('Positions closed successfully')"
                    class="px-4 py-2 bg-tv-red text-white text-sm font-medium rounded hover:bg-tv-red/80 transition-colors">
              Confirm Close
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ================================================================
       TOAST NOTIFICATION
       ================================================================ -->
  <Teleport to="body">
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="translate-y-full opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="translate-y-full opacity-0"
    >
      <div v-if="toastVisible"
           class="fixed bottom-5 right-5 z-[110] bg-tv-panel border border-tv-border rounded-lg shadow-lg px-4 py-3 flex items-center gap-3 max-w-sm">
        <i class="fas fa-check-circle text-tv-green"></i>
        <span class="text-sm text-tv-text">{{ toastMessage }}</span>
        <button @click="toastVisible = false" class="text-tv-muted hover:text-tv-text transition-colors ml-2">
          <i class="fas fa-xmark text-xs"></i>
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* Font comparison — load additional mono fonts (scoped to this page) */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Fira+Code:wght@400;500&family=Space+Mono:wght@400;700&family=DM+Mono:wght@400;500&family=Inconsolata:wght@400;500&display=swap');
</style>
