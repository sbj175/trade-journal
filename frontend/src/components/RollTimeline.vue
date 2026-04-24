<script setup>
import { ref, computed } from 'vue'
import { formatNumber, formatDate, formatExpirationShort } from '@/lib/formatters'
import BaseIcon from '@/components/BaseIcon.vue'

const props = defineProps({
  timeline: Object,
  // Which section kinds to render and in what order.
  // Ledger uses the default (all three); Positions passes ['roll', 'opening'].
  show: {
    type: Array,
    default: () => ['closing', 'roll', 'opening'],
  },
})

// Sections assembled per the `show` prop. Within the 'roll' slot, events
// render in descending chronology (newest first).
const sections = computed(() => {
  if (!props.timeline) return []
  const out = []
  for (const kind of props.show) {
    if (kind === 'closing' && props.timeline.closing) {
      out.push(props.timeline.closing)
    } else if (kind === 'roll') {
      const rolls = [...(props.timeline.roll_events || [])].reverse()
      out.push(...rolls)
    } else if (kind === 'opening' && props.timeline.opening) {
      out.push(props.timeline.opening)
    }
  }
  return out
})

const expandedKeys = ref(new Set())
function toggle(key) {
  if (expandedKeys.value.has(key)) expandedKeys.value.delete(key)
  else expandedKeys.value.add(key)
  expandedKeys.value = new Set(expandedKeys.value)
}

function sectionTitle(kind) {
  if (kind === 'OPENING') return 'Opening'
  if (kind === 'CLOSING') return 'Closing'
  return 'Roll'
}

function sectionKey(section, idx) {
  return `${section.kind}-${idx}-${section.date || ''}`
}

function signedAmount(n) {
  if (n == null) return ''
  const sign = n > 0 ? '+' : (n < 0 ? '−' : '')
  return `${sign}$${formatNumber(Math.abs(n))}${n > 0 ? ' cr' : (n < 0 ? ' db' : '')}`
}

function amountClass(n) {
  if (n == null) return 'text-tv-muted'
  if (n > 0) return 'text-tv-green'
  if (n < 0) return 'text-tv-red'
  return 'text-tv-muted'
}

function legActionLabel(leg) {
  // leg.sign: +1 long, -1 short.  leg.kind: OPEN or CLOSE.
  if (leg.kind === 'OPEN') return leg.sign > 0 ? 'BTO' : 'STO'
  // CLOSE
  if (leg.closing_type === 'EXPIRATION') return 'EXP'
  if (leg.closing_type === 'EXERCISE') return 'EXR'
  if (leg.closing_type === 'ASSIGNMENT') return 'ASN'
  return leg.sign > 0 ? 'STC' : 'BTC'
}

function legQtyDisplay(leg) {
  const s = leg.sign > 0 ? '+' : '-'
  return `${s}${leg.quantity}`
}

function optionTypeLabel(t) {
  const c = (t || '').toUpperCase()[0] || ''
  if (c === 'C') return 'Call'
  if (c === 'P') return 'Put'
  return '—'
}
</script>

<template>
  <div class="space-y-0" v-if="sections.length">
    <template v-for="(section, idx) in sections" :key="sectionKey(section, idx)">
      <!-- Section divider (not before first) -->
      <div v-if="idx > 0" class="border-t border-tv-border/40 my-3"></div>

      <!-- ROLL section: one-line on desktop; date/amount row + strike transition row on mobile -->
      <template v-if="section.kind === 'ROLL'">
        <div class="cursor-pointer hover:bg-tv-border/15 rounded transition-colors px-2 py-2"
             @click="toggle(sectionKey(section, idx))">
          <div class="flex items-center justify-between gap-3">
            <div class="flex items-center gap-2 min-w-0">
              <BaseIcon name="chevron-right" size="xs"
                        class="text-tv-muted transition-transform"
                        :class="expandedKeys.has(sectionKey(section, idx)) ? 'rotate-90' : ''" />
              <span class="text-sm font-semibold uppercase tracking-wide text-tv-cyan">
                {{ sectionTitle(section.kind) }}
              </span>
              <span class="text-tv-muted text-sm whitespace-nowrap">{{ section.date ? formatDate(section.date) : '—' }}</span>
              <span class="hidden sm:inline font-mono text-sm ml-2 truncate">
                <span class="text-tv-text">{{ section.closed_strikes_label || '—' }}</span>
                <span class="text-tv-muted mx-1.5">→</span>
                <span class="text-tv-text">{{ section.opened_strikes_label || '—' }}</span>
              </span>
            </div>
            <span class="text-sm font-mono shrink-0" :class="amountClass(section.net_credit_debit)">
              {{ signedAmount(section.net_credit_debit) }}
            </span>
          </div>
          <!-- Strike transition wraps to its own row below on mobile -->
          <div class="sm:hidden font-mono text-sm ml-6 mt-0.5">
            <span class="text-tv-text">{{ section.closed_strikes_label || '—' }}</span>
            <span class="text-tv-muted mx-1.5">→</span>
            <span class="text-tv-text">{{ section.opened_strikes_label || '—' }}</span>
          </div>
        </div>
        <!-- Per-leg pair rows (indented to match the summary) -->
        <div v-if="expandedKeys.has(sectionKey(section, idx))" class="px-4 pb-2 mt-1 space-y-1">
          <div v-for="(p, pi) in section.pairs" :key="'pair-' + pi"
               class="font-mono text-xs text-tv-muted flex items-center flex-wrap gap-x-2 gap-y-0.5">
            <span class="w-10 text-right" :class="p.sign > 0 ? 'text-tv-green' : 'text-tv-red'">
              {{ (p.sign > 0 ? '+' : '-') + p.quantity }}
            </span>
            <span class="text-tv-text">{{ p.expiration ? formatExpirationShort(p.expiration) : '—' }}</span>
            <span class="text-tv-text">{{ optionTypeLabel(p.option_type) }}</span>
            <span>{{ p.closed.strike }}</span>
            <span class="text-tv-muted">@{{ formatNumber(p.closed.price) }}</span>
            <span class="text-tv-muted">→</span>
            <span>{{ p.opened.strike }}</span>
            <span class="text-tv-muted">@{{ formatNumber(p.opened.price) }}</span>
            <span v-if="(p.closed.fees || p.opened.fees)" class="text-tv-muted ml-2">
              fees ${{ formatNumber(Math.abs((p.closed.fees || 0) + (p.opened.fees || 0))) }}
            </span>
          </div>
        </div>
      </template>

      <!-- OPENING / CLOSING sections: static header + leg rows -->
      <template v-else>
        <div class="flex items-center justify-between px-2 py-2">
          <div class="flex items-center gap-2">
            <span class="text-sm font-semibold uppercase tracking-wide"
                  :class="section.kind === 'OPENING' ? 'text-tv-green' : 'text-tv-muted'">
              {{ sectionTitle(section.kind) }}
            </span>
            <span class="text-tv-muted text-sm">{{ section.date ? formatDate(section.date) : '—' }}</span>
          </div>
          <span class="text-sm font-mono" :class="amountClass(section.net_credit_debit)">
            {{ signedAmount(section.net_credit_debit) }}
          </span>
        </div>
        <div class="px-4 pb-2 space-y-0.5">
          <div v-for="(leg, li) in section.legs" :key="'leg-' + idx + '-' + li"
               class="font-mono text-xs flex items-center flex-wrap gap-x-2">
            <span class="w-10 text-right font-medium"
                  :class="leg.sign > 0 ? 'text-tv-green' : 'text-tv-red'">
              {{ legQtyDisplay(leg) }}
            </span>
            <span class="text-tv-text w-14">{{ leg.expiration ? formatExpirationShort(leg.expiration) : '—' }}</span>
            <span class="text-tv-text w-14">{{ leg.strike }}{{ (leg.option_type || '').toUpperCase()[0] }}</span>
            <span class="text-tv-muted uppercase tracking-wider w-10">{{ legActionLabel(leg) }}</span>
            <span class="text-tv-muted">@{{ formatNumber(leg.price) }}</span>
            <span v-if="leg.fees" class="text-tv-muted ml-2">fees ${{ formatNumber(Math.abs(leg.fees)) }}</span>
          </div>
        </div>
      </template>
    </template>
  </div>

  <!-- Fallback when timeline has no events (e.g., equity-only group) -->
  <div v-else class="text-xs text-tv-muted px-4 py-2">
    No option activity to stage.
  </div>
</template>
