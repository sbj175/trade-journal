<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatDate } from '@/lib/formatters'

const Auth = useAuth()

const props = defineProps({
  groupId: { type: String, default: null },
  underlying: { type: String, default: '' },
})

const emit = defineEmits(['close'])

const loading = ref(false)
const error = ref(null)
const chain = ref(null)

const cumulativePnl = () => {
  if (!chain.value?.chain?.length) return 0
  return chain.value.chain[chain.value.chain.length - 1]?.cumulative_pnl || 0
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
             class="px-5 py-3 border-t border-tv-border/50 flex items-center justify-end">
          <span class="text-sm font-medium"
                :class="cumulativePnl() >= 0 ? 'text-tv-green' : 'text-tv-red'">
            Cumulative P&amp;L: ${{ formatNumber(cumulativePnl()) }}
          </span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
