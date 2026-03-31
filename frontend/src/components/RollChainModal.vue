<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatDate } from '@/lib/formatters'

const Auth = useAuth()

const props = defineProps({
  groupId: { type: String, default: null },
  underlying: { type: String, default: '' },
  openPnl: { type: Number, default: null },
})

const emit = defineEmits(['close'])

const loading = ref(false)
const error = ref(null)
const chain = ref(null)
const showLearnMore = ref(false)

const cumulativePnl = () => {
  if (!chain.value?.chain?.length) return 0
  return chain.value.chain[chain.value.chain.length - 1]?.cumulative_pnl || 0
}

const netPremium = () => {
  return chain.value?.net_premium || 0
}

const unrealizedPnl = () => {
  // Prefer live value from prop, fall back to API (cached quotes)
  if (props.openPnl !== null) return props.openPnl
  return chain.value?.unrealized_pnl ?? null
}

async function loadChain(gid) {
  if (!gid) return
  loading.value = true
  error.value = null
  chain.value = null
  try {
    const resp = await Auth.authFetch(`/api/ledger/group-roll-chain/${gid}`)
    if (!resp.ok) {
      const text = await resp.text()
      console.error('Roll chain API error:', resp.status, text)
      error.value = `API error (${resp.status})`
      return
    }
    chain.value = await resp.json()
  } catch (e) {
    error.value = 'Failed to load roll chain'
    console.error('Error loading roll chain:', e)
  } finally {
    loading.value = false
  }
}

function onKeydown(e) {
  if (e.key === 'Escape' && props.groupId) {
    emit('close')
  }
}

watch(() => props.groupId, (gid) => {
  if (gid) loadChain(gid)
}, { immediate: true })

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="groupId" class="fixed inset-0 z-[100] flex items-center justify-center">
      <!-- Backdrop -->
      <div class="absolute inset-0 bg-black/60" @click="$emit('close')"></div>
      <!-- Modal content -->
      <div class="relative bg-tv-panel border border-tv-border rounded-lg shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] overflow-hidden flex flex-col">
        <!-- Header -->
        <div class="px-5 py-4 flex items-center justify-between border-b border-tv-border/50">
          <span class="flex items-center gap-3">
            <i class="fas fa-link text-tv-blue"></i>
            <span class="text-tv-text font-semibold text-lg">Roll Chain</span>
            <span v-if="underlying" class="text-tv-muted text-base">&mdash; {{ underlying }}</span>
            <span v-if="chain" class="text-tv-muted text-sm">
              ({{ chain.chain_length }} {{ chain.chain_length === 1 ? 'group' : 'groups' }})
            </span>
          </span>
          <button @click="$emit('close')" class="text-tv-muted hover:text-tv-text text-lg w-8 h-8 flex items-center justify-center rounded hover:bg-tv-border/30 transition-colors">
            <i class="fas fa-times"></i>
          </button>
        </div>
        <!-- Body -->
        <div class="overflow-y-auto flex-1">
          <div v-if="loading" class="px-5 py-8 text-tv-muted text-sm text-center">
            <div class="spinner mx-auto mb-3" style="width: 24px; height: 24px; border-width: 2px;"></div>
            Loading roll chain...
          </div>
          <div v-else-if="error" class="px-5 py-8 text-tv-red text-sm text-center">
            {{ error }}
          </div>
          <template v-else-if="chain">
            <!-- Column headers -->
            <div class="flex items-center px-5 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border/30">
              <span class="w-6"></span>
              <span class="w-28">Opened</span>
              <span class="w-6"></span>
              <span class="w-28">Closed</span>
              <span class="w-36 ml-4">Strategy</span>
              <span class="w-16 text-center">Status</span>
              <span class="ml-auto text-right">Realized</span>
            </div>
            <div class="divide-y divide-tv-border/20">
              <div v-for="(item, idx) in chain.chain.slice().reverse()" :key="item.group_id"
                   class="flex items-center px-5 py-2.5 text-sm"
                   :class="item.group_id === groupId ? 'bg-tv-blue/10' : ''">
                <span class="w-6 text-tv-muted text-xs">{{ chain.chain.length - idx }}.</span>
                <span class="w-28 text-tv-muted">{{ formatDate(item.opening_date) }}</span>
                <span class="w-6 text-tv-muted text-center">&rarr;</span>
                <span class="w-28 text-tv-muted">{{ item.closing_date ? formatDate(item.closing_date) : '(open)' }}</span>
                <span class="w-36 text-tv-text ml-4">{{ item.strategy_label || '\u2014' }}</span>
                <span class="w-16 text-xs px-1.5 py-0.5 rounded text-center"
                      :class="item.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-muted/20 text-tv-muted'">
                  {{ item.status }}
                </span>
                <span class="ml-auto text-sm font-medium"
                      :class="item.realized_pnl > 0 ? 'text-tv-green' : item.realized_pnl < 0 ? 'text-tv-red' : 'text-tv-muted'">
                  {{ item.realized_pnl ? '$' + formatNumber(item.realized_pnl) : '\u2014' }}
                </span>
              </div>
            </div>
          </template>
        </div>
        <!-- Footer -->
        <div v-if="chain"
             class="px-5 py-3 border-t border-tv-border/50 flex flex-col gap-1.5">
          <div class="flex items-start justify-between">
            <div class="text-sm text-tv-muted">
              Net Premium: <span class="font-medium text-tv-text">${{ formatNumber(netPremium()) }}</span>
            </div>
            <div class="flex flex-col items-end gap-0.5">
              <div class="flex items-center justify-between w-48 text-sm">
                <span class="text-tv-muted">Chain P&amp;L:</span>
                <span class="font-medium" :class="cumulativePnl() >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(cumulativePnl()) }}</span>
              </div>
              <div v-if="unrealizedPnl() !== null" class="flex items-center justify-between w-48 text-sm">
                <span class="text-tv-muted">Unrealized:</span>
                <span class="font-medium" :class="unrealizedPnl() >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(unrealizedPnl()) }}</span>
              </div>
              <div v-if="unrealizedPnl() !== null" class="w-48 border-t border-tv-border/50 mt-0.5 pt-1">
                <div class="flex items-center justify-between text-sm">
                  <span class="text-tv-muted">Chain Total:</span>
                  <span class="font-semibold" :class="(cumulativePnl() + unrealizedPnl()) >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(cumulativePnl() + unrealizedPnl()) }}</span>
                </div>
              </div>
            </div>
          </div>
          <!-- Learn More -->
          <div class="border-t border-tv-border/30 mt-2 pt-2">
            <button @click="showLearnMore = !showLearnMore"
                    class="text-xs text-tv-blue hover:text-tv-blue/80 transition-colors cursor-pointer">
              <i class="fas fa-info-circle mr-1"></i>{{ showLearnMore ? 'Hide' : 'Learn more about roll detection' }}
            </button>
            <div v-if="showLearnMore" class="mt-2 text-xs text-tv-muted leading-relaxed space-y-1.5">
              <p>A <span class="text-tv-text font-medium">roll</span> is automatically detected when a position is closed and a new position is opened on the <span class="text-tv-text">same account, underlying, and option type on the same day</span>.</p>
              <p>Multi-leg strategies (e.g. vertical spreads) are fully supported — each leg is matched independently, so rolling a spread counts as a single roll.</p>
              <p><span class="text-tv-text font-medium">Net Premium</span> — total premium collected across all positions in the chain.</p>
              <p><span class="text-tv-text font-medium">Chain P&amp;L</span> — cumulative realized P&amp;L from all closed positions in the chain.</p>
              <p><span class="text-tv-text font-medium">Unrealized</span> — the current open position&apos;s unrealized P&amp;L based on live market prices.</p>
              <p><span class="text-tv-text font-medium">Chain Total</span> — Chain P&amp;L plus Unrealized. This is where you stand on the entire trade sequence right now.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
