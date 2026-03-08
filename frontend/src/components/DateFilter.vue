<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  storageKey: { type: String, default: 'dateFilter' },
  defaultPreset: { type: String, default: '30 days' },
})

const emit = defineEmits(['update'])

// --- Presets ---
const PRESETS = [
  'This Week', 'This Month', 'Last Month',
  'This Quarter', 'Last Quarter', 'YTD',
  'Last 30 Days', 'Last 90 Days', 'Custom',
]

// --- State ---
const open = ref(false)
const activePreset = ref('')
const fromDate = ref(null)   // Date object or null
const toDate = ref(null)     // Date object or null
const customMode = ref(false)
const selectingField = ref(null) // 'from' | 'to' | null
const viewYear = ref(new Date().getFullYear())
const viewMonth = ref(new Date().getMonth())
const dropdownRef = ref(null)
const triggerRef = ref(null)

// --- Helpers ---
function today() {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function addDays(d, n) {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

function sameDay(a, b) {
  if (!a || !b) return false
  return a.getFullYear() === b.getFullYear() &&
         a.getMonth() === b.getMonth() &&
         a.getDate() === b.getDate()
}

function inRange(d, from, to) {
  if (!from || !to || !d) return false
  const t = d.getTime()
  return t >= from.getTime() && t <= to.getTime()
}

function fmt(d) {
  if (!d) return ''
  return `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}`
}

function startOfWeek(d) {
  const day = d.getDay() // 0=Sun
  const diff = day === 0 ? 6 : day - 1 // Monday-based
  return addDays(d, -diff)
}

function quarterStart(d) {
  const q = Math.floor(d.getMonth() / 3)
  return new Date(d.getFullYear(), q * 3, 1)
}

function computeFromDate(preset) {
  const t = today()
  switch (preset) {
    case 'This Week':     return startOfWeek(t)
    case 'This Month':    return new Date(t.getFullYear(), t.getMonth(), 1)
    case 'Last Month':    return new Date(t.getFullYear(), t.getMonth() - 1, 1)
    case 'This Quarter':  return quarterStart(t)
    case 'Last Quarter': {
      const qs = quarterStart(t)
      return new Date(qs.getFullYear(), qs.getMonth() - 3, 1)
    }
    case 'YTD':           return new Date(t.getFullYear(), 0, 1)
    case 'Last 30 Days':  return addDays(t, -30)
    case 'Last 90 Days':  return addDays(t, -90)
    default:              return null
  }
}

function computeToDate(preset) {
  const t = today()
  switch (preset) {
    case 'Last Month':
      return new Date(t.getFullYear(), t.getMonth(), 0) // last day of prev month
    case 'Last Quarter': {
      const qs = quarterStart(t)
      return new Date(qs.getFullYear(), qs.getMonth(), 0) // last day before quarter start
    }
    default:
      return t
  }
}

// --- Calendar ---
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const monthLabel = computed(() => `${MONTH_NAMES[viewMonth.value]} ${viewYear.value}`)

const calendarDays = computed(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  const startDay = first.getDay() // 0=Sun
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()

  const cells = []
  // Leading days from previous month
  const prevMonthDays = new Date(viewYear.value, viewMonth.value, 0).getDate()
  for (let i = startDay - 1; i >= 0; i--) {
    cells.push({
      date: new Date(viewYear.value, viewMonth.value - 1, prevMonthDays - i),
      currentMonth: false,
    })
  }
  // Current month
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({
      date: new Date(viewYear.value, viewMonth.value, d),
      currentMonth: true,
    })
  }
  // Trailing days
  const remaining = 42 - cells.length
  for (let d = 1; d <= remaining; d++) {
    cells.push({
      date: new Date(viewYear.value, viewMonth.value + 1, d),
      currentMonth: false,
    })
  }
  return cells
})

// --- Display ---
const displayRange = computed(() => {
  if (!fromDate.value && !toDate.value) return 'Select dates'
  return `${fmt(fromDate.value)} - ${fmt(toDate.value)}`
})

// --- Actions ---
function selectPreset(preset) {
  if (preset === 'Custom') {
    customMode.value = true
    activePreset.value = 'Custom'
    selectingField.value = 'from'
    saveState()
    return
  }
  customMode.value = false
  selectingField.value = null
  activePreset.value = preset
  fromDate.value = computeFromDate(preset)
  toDate.value = computeToDate(preset)
  scrollCalendarToDate(fromDate.value)
  saveState()
  emitUpdate()
}

function scrollCalendarToDate(d) {
  if (!d) return
  // Show the month that contains toDate (today usually)
  const to = toDate.value || today()
  viewYear.value = to.getFullYear()
  viewMonth.value = to.getMonth()
}

function clickFromDate() {
  if (!customMode.value) return
  selectingField.value = selectingField.value === 'from' ? null : 'from'
}

function clickToDate() {
  if (!customMode.value) return
  selectingField.value = selectingField.value === 'to' ? null : 'to'
}

function clickCalendarDay(cell) {
  if (!customMode.value) return
  if (isFuture(cell.date)) return

  if (!selectingField.value) {
    // Click anywhere on calendar starts a new from selection
    selectingField.value = 'from'
  }

  if (selectingField.value === 'from') {
    fromDate.value = cell.date
    // Default to=today, user can refine with next click
    if (!toDate.value || cell.date.getTime() > toDate.value.getTime()) {
      toDate.value = today()
    }
    selectingField.value = 'to'  // auto-advance to To
    saveState()
    emitUpdate()
  } else if (selectingField.value === 'to') {
    toDate.value = cell.date
    // If to < from, swap them
    if (fromDate.value && cell.date.getTime() < fromDate.value.getTime()) {
      const tmp = fromDate.value
      fromDate.value = cell.date
      toDate.value = tmp
    }
    selectingField.value = null  // done
    saveState()
    emitUpdate()
  }
}

function prevMonth() {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value--
  } else {
    viewMonth.value--
  }
}

function nextMonth() {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value++
  } else {
    viewMonth.value++
  }
}

function prevYear() { viewYear.value-- }
function nextYear() { viewYear.value++ }

function toggle() {
  open.value = !open.value
  if (open.value) {
    const target = toDate.value || today()
    viewYear.value = target.getFullYear()
    viewMonth.value = target.getMonth()
  }
}

function close() {
  open.value = false
  selectingField.value = null
}

// --- Persistence ---
function saveState() {
  const state = {
    preset: activePreset.value,
    from: fromDate.value ? fromDate.value.toISOString() : null,
    to: toDate.value ? toDate.value.toISOString() : null,
    customMode: customMode.value,
  }
  localStorage.setItem(props.storageKey, JSON.stringify(state))
}

function loadState() {
  const raw = localStorage.getItem(props.storageKey)
  if (raw) {
    try {
      const state = JSON.parse(raw)
      activePreset.value = state.preset || props.defaultPreset
      customMode.value = state.customMode || false

      if (customMode.value && state.from && state.to) {
        fromDate.value = new Date(state.from)
        toDate.value = new Date(state.to)
      } else if (activePreset.value && activePreset.value !== 'Custom') {
        // Recompute relative dates so they stay fresh
        fromDate.value = computeFromDate(activePreset.value)
        toDate.value = computeToDate(activePreset.value)
      }
      return
    } catch { /* fall through */ }
  }
  // Default
  activePreset.value = props.defaultPreset
  fromDate.value = computeFromDate(props.defaultPreset)
  toDate.value = computeToDate(props.defaultPreset)
}

function clear() {
  activePreset.value = ''
  customMode.value = false
  selectingField.value = null
  fromDate.value = null
  toDate.value = null
  localStorage.removeItem(props.storageKey)
  emitUpdate()
}

defineExpose({ clear })

function emitUpdate() {
  emit('update', {
    from: fromDate.value ? fromDate.value.toISOString().slice(0, 10) : null,
    to: toDate.value ? toDate.value.toISOString().slice(0, 10) : null,
  })
}

// --- Click outside ---
function onClickOutside(e) {
  if (!open.value) return
  const dropdown = dropdownRef.value
  const trigger = triggerRef.value
  if (dropdown && !dropdown.contains(e.target) &&
      trigger && !trigger.contains(e.target)) {
    close()
  }
}

function onKeydown(e) {
  if (e.key === 'Escape' && open.value) {
    close()
  }
}

onMounted(() => {
  loadState()
  emitUpdate()
  document.addEventListener('mousedown', onClickOutside)
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', onClickOutside)
  document.removeEventListener('keydown', onKeydown)
})

// --- Cell styling helpers ---
function isToday(d) { return sameDay(d, today()) }
function isFuture(d) { return d.getTime() > today().getTime() }

function isRangeStart(d) { return sameDay(d, fromDate.value) }
function isRangeEnd(d) { return sameDay(d, toDate.value) }
function isInRange(d) { return inRange(d, fromDate.value, toDate.value) }
function isRangeSingle() { return sameDay(fromDate.value, toDate.value) }
</script>

<template>
  <div class="relative inline-block">
    <!-- Dormant trigger -->
    <div ref="triggerRef"
         @click="toggle"
         class="flex items-center gap-2 px-4 py-2 bg-tv-panel border border-tv-border rounded cursor-pointer
                hover:border-tv-blue/50 transition-colors select-none"
         :class="open ? 'border-tv-blue/50' : ''">
      <span class="text-tv-muted text-xs tracking-wide uppercase">Date Filter</span>
      <span class="text-tv-text font-mono text-sm">{{ displayRange }}</span>
      <svg class="w-4 h-4 text-tv-muted ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
      <button v-if="fromDate || toDate"
              @click.stop="clear"
              class="ml-1 w-5 h-5 flex items-center justify-center text-tv-muted hover:text-tv-text hover:bg-tv-hover rounded transition-colors"
              title="Clear date filter">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Dropdown -->
    <div v-if="open" ref="dropdownRef"
         class="absolute top-full left-0 mt-1 z-50 flex bg-tv-panel border border-tv-border rounded shadow-2xl shadow-black/50">

      <!-- Left: Presets -->
      <div class="w-40 border-r border-tv-border py-2 flex flex-col">
        <button v-for="preset in PRESETS" :key="preset"
                @click="selectPreset(preset)"
                class="text-left px-4 py-2.5 text-sm transition-colors"
                :class="activePreset === preset
                  ? 'bg-tv-blue/30 text-tv-blue border-l-2 border-tv-blue'
                  : 'text-tv-text hover:bg-tv-hover border-l-2 border-transparent'">
          {{ preset }}
        </button>
      </div>

      <!-- Right: Calendar -->
      <div class="w-[310px] p-4 flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between mb-3">
          <span class="text-tv-muted text-xs tracking-wide uppercase">Selected Date Range</span>
          <button @click="close" class="text-tv-muted hover:text-tv-text transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Month navigation -->
        <div class="flex items-center justify-between mb-3">
          <div class="flex gap-1">
            <button @click="prevYear" class="w-7 h-7 flex items-center justify-center text-tv-muted hover:text-tv-text hover:bg-tv-hover rounded transition-colors text-xs font-bold">&laquo;</button>
            <button @click="prevMonth" class="w-7 h-7 flex items-center justify-center text-tv-muted hover:text-tv-text hover:bg-tv-hover rounded transition-colors text-xs font-bold">&lsaquo;</button>
          </div>
          <span class="text-tv-text font-medium text-sm">{{ monthLabel }}</span>
          <div class="flex gap-1">
            <button @click="nextMonth" class="w-7 h-7 flex items-center justify-center text-tv-muted hover:text-tv-text hover:bg-tv-hover rounded transition-colors text-xs font-bold">&rsaquo;</button>
            <button @click="nextYear" class="w-7 h-7 flex items-center justify-center text-tv-muted hover:text-tv-text hover:bg-tv-hover rounded transition-colors text-xs font-bold">&raquo;</button>
          </div>
        </div>

        <!-- Day headers -->
        <div class="grid grid-cols-7 mb-1">
          <div v-for="day in ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']" :key="day"
               class="text-center text-tv-muted text-xs py-1">{{ day }}</div>
        </div>

        <!-- Day cells -->
        <div class="grid grid-cols-7">
          <button v-for="(cell, i) in calendarDays" :key="i"
                  @click="clickCalendarDay(cell)"
                  class="h-9 flex items-center justify-center text-sm transition-colors relative"
                  :class="[
                    // Base text color
                    isFuture(cell.date) ? 'text-tv-muted/20 cursor-default'
                      : cell.currentMonth ? 'text-tv-text' : 'text-tv-muted/40',
                    // Custom mode cursor
                    !isFuture(cell.date) && customMode && selectingField ? 'cursor-pointer' : !isFuture(cell.date) && customMode ? 'cursor-default' : 'cursor-default',
                    // Range background (middle days)
                    isInRange(cell.date) && !isRangeStart(cell.date) && !isRangeEnd(cell.date) && !isRangeSingle()
                      ? 'bg-tv-blue/15'
                      : '',
                    // Range start
                    isRangeStart(cell.date) && !isRangeSingle()
                      ? 'bg-tv-blue/15 rounded-l-full'
                      : '',
                    // Range end
                    isRangeEnd(cell.date) && !isRangeSingle()
                      ? 'bg-tv-blue/15 rounded-r-full'
                      : '',
                  ]">
            <!-- Day number with circle for today / range endpoints -->
            <span class="w-8 h-8 flex items-center justify-center rounded-full transition-colors"
                  :class="[
                    isRangeStart(cell.date) || isRangeEnd(cell.date)
                      ? 'bg-tv-blue/30 text-tv-blue font-medium'
                      : '',
                    isToday(cell.date) && !isRangeStart(cell.date) && !isRangeEnd(cell.date)
                      ? 'ring-1 ring-tv-muted/50'
                      : '',
                  ]">
              {{ cell.date.getDate() }}
            </span>
          </button>
        </div>

        <!-- From / To footer -->
        <div class="flex items-center mt-4 pt-3 border-t border-tv-border">
          <div class="flex-1">
            <div class="text-tv-muted text-xs mb-1">From</div>
            <button @click="clickFromDate"
                    class="font-mono text-sm transition-colors"
                    :class="[
                      customMode ? 'cursor-pointer hover:text-tv-blue' : 'cursor-default',
                      selectingField === 'from'
                        ? 'text-tv-blue'
                        : customMode ? 'text-tv-text' : 'text-tv-muted',
                    ]">
              {{ selectingField === 'from' ? 'Select date' : fmt(fromDate) || '--' }}
            </button>
          </div>
          <svg class="w-4 h-4 text-tv-muted mx-3 mt-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <div class="flex-1 text-right">
            <div class="text-tv-muted text-xs mb-1">To</div>
            <button @click="clickToDate"
                    class="font-mono text-sm transition-colors"
                    :class="[
                      customMode ? 'cursor-pointer hover:text-tv-blue' : 'cursor-default',
                      selectingField === 'to'
                        ? 'text-tv-blue'
                        : customMode ? 'text-tv-text' : 'text-tv-muted',
                    ]">
              {{ selectingField === 'to' ? 'Select date' : fmt(toDate) || '--' }}
            </button>
          </div>
          <svg class="w-4 h-4 text-tv-muted ml-3 mt-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
        </div>
      </div>
    </div>
  </div>
</template>
