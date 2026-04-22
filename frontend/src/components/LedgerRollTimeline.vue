<script setup>
import { ref, computed } from 'vue'
import { formatNumber, formatDate, formatExpirationShort } from '@/lib/formatters'
import BaseIcon from '@/components/BaseIcon.vue'

const props = defineProps({
  timeline: Object,
})

// Sections in descending chronological order (closing first, opening last)
const sections = computed(() => {
  if (!props.timeline) return []
  const out = []
  if (props.timeline.closing) out.push(props.timeline.closing)
  // Roll events are in chronological ASC order from backend; reverse for DESC display
  const rolls = [...(props.timeline.roll_events || [])].reverse()
  out.push(...rolls)
  if (props.timeline.opening) out.push(props.timeline.opening)
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

      <!-- Section header -->
      <div class="flex items-center justify-between px-2 py-2">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold uppercase tracking-wide"
                :class="section.kind === 'ROLL' ? 'text-tv-cyan'
                       : section.kind === 'OPENING' ? 'text-tv-green'
                       : 'text-tv-muted'">
            {{ sectionTitle(section.kind) }}
          </span>
          <span class="text-tv-muted text-sm">{{ section.date ? formatDate(section.date) : '—' }}</span>
        </div>
        <span class="text-sm font-mono" :class="amountClass(section.net_credit_debit)">
          {{ signedAmount(section.net_credit_debit) }}
        </span>
      </div>

      <!-- ROLL section body: ROLLED X → Y summary + expand-for-details -->
      <template v-if="section.kind === 'ROLL'">
        <div class="px-4 pb-2">
          <div class="flex items-center justify-between">
            <div class="font-mono text-sm">
              <span class="uppercase tracking-wider text-tv-muted text-xs mr-2">Rolled</span>
              <span class="text-tv-text">{{ section.closed_strikes_label || '—' }}</span>
              <span class="text-tv-muted mx-2">→</span>
              <span class="text-tv-text">{{ section.opened_strikes_label || '—' }}</span>
            </div>
            <button class="text-xs text-tv-muted hover:text-tv-blue flex items-center gap-1"
                    @click="toggle(sectionKey(section, idx))">
              <BaseIcon name="chevron-right" size="xs"
                        :class="expandedKeys.has(sectionKey(section, idx)) ? 'rotate-90' : ''"
                        class="transition-transform" />
              <span>{{ expandedKeys.has(sectionKey(section, idx)) ? 'Hide legs' : 'Show legs' }}</span>
            </button>
          </div>
          <!-- Per-leg pair rows -->
          <div v-if="expandedKeys.has(sectionKey(section, idx))" class="mt-2 space-y-1">
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
        </div>
      </template>

      <!-- OPENING / CLOSING section body: per-leg rows -->
      <template v-else>
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
