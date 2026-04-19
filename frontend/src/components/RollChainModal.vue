<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import { formatNumber, formatDate } from '@/lib/formatters'
import BaseButton from '@/components/BaseButton.vue'
import BaseIcon from '@/components/BaseIcon.vue'

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

const isOpen = computed(() => !!props.groupId)
useBackDismiss(isOpen, () => emit('close'))

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
            <BaseIcon name="link" class="text-tv-blue" />
            <span class="text-tv-text font-semibold text-lg">Roll Chain</span>
            <span v-if="underlying" class="text-tv-muted text-base">&mdash; {{ underlying }}</span>
            <span v-if="chain && chain.chain.length" class="text-tv-muted text-base">
              {{ chain.chain[0].strategy_label || '' }}
            </span>
          </span>
          <BaseButton variant="ghost" size="md" icon="times" @click="$emit('close')" class="w-8 h-8 justify-center" />
        </div>
        <!-- Body -->
        <div class="overflow-y-auto flex-1">
          <div v-if="loading" class="px-5 py-8 text-tv-muted text-sm text-center">
            <div class="spinner mx-auto mb-3 w-6 h-6 border-2"></div>
            Loading roll chain...
          </div>
          <div v-else-if="error" class="px-5 py-8 text-tv-red text-sm text-center">
            {{ error }}
          </div>
          <template v-else-if="chain">
            <table class="min-w-full table-auto border-collapse text-sm">
              <thead>
                <tr class="text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border/30">
                  <th class="px-5 py-2 text-left font-normal w-6 hidden md:table-cell"></th>
                  <th class="py-2 text-left font-normal">Opened</th>
                  <th class="py-2 text-center font-normal w-6"></th>
                  <th class="py-2 text-left font-normal">Closed</th>
                  <th class="py-2 text-right font-normal">Premium</th>
                  <th class="px-5 py-2 text-right font-normal">Realized</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in chain.chain.slice().reverse()" :key="item.group_id"
                    class="border-b border-tv-border/20"
                    :class="item.group_id === groupId ? 'bg-tv-blue/10' : ''">
                  <td class="px-5 py-2.5 text-tv-muted text-xs hidden md:table-cell">{{ chain.chain.length - idx }}.</td>
                  <td class="py-2.5 text-tv-muted">{{ formatDate(item.opening_date) }}</td>
                  <td class="py-2.5 text-tv-muted text-center">&rarr;</td>
                  <td class="py-2.5 text-tv-muted">{{ item.closing_date ? formatDate(item.closing_date) : '(open)' }}</td>
                  <td class="py-2.5 text-right font-medium"
                      :class="(item.premium || 0) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                    {{ item.premium != null ? '$' + formatNumber(item.premium) : '\u2014' }}
                  </td>
                  <td class="px-5 py-2.5 text-right font-medium"
                      :class="item.realized_pnl > 0 ? 'text-tv-green' : item.realized_pnl < 0 ? 'text-tv-red' : 'text-tv-muted'">
                    {{ item.realized_pnl ? '$' + formatNumber(item.realized_pnl) : '\u2014' }}
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="border-t border-tv-border/50">
                  <td class="hidden md:table-cell"></td>
                  <td colspan="3"></td>
                  <td class="py-2.5 text-right text-sm text-tv-muted cursor-help" title="Total realized P&L across all positions in the chain">Chain Realized:</td>
                  <td class="px-5 py-2.5 text-right text-sm font-medium" :class="cumulativePnl() >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(cumulativePnl()) }}</td>
                </tr>
                <tr v-if="unrealizedPnl() !== null">
                  <td class="hidden md:table-cell"></td>
                  <td colspan="3"></td>
                  <td class="py-1 text-right text-sm text-tv-muted cursor-help" title="Current open position's unrealized P&L based on live market prices">Unrealized:</td>
                  <td class="px-5 py-1 text-right text-sm font-medium" :class="unrealizedPnl() >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(unrealizedPnl()) }}</td>
                </tr>
                <tr v-if="unrealizedPnl() !== null" class="border-t border-tv-border/50">
                  <td class="hidden md:table-cell"></td>
                  <td colspan="3"></td>
                  <td class="py-2.5 text-right text-sm text-tv-muted cursor-help" title="Chain Realized plus Unrealized — where you stand on the entire trade sequence right now">Chain Total:</td>
                  <td class="px-5 py-2.5 text-right text-sm font-semibold" :class="(cumulativePnl() + unrealizedPnl()) >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(cumulativePnl() + unrealizedPnl()) }}</td>
                </tr>
              </tfoot>
            </table>
          </template>
        </div>
        <!-- Footer -->
        <div v-if="chain"
             class="px-5 py-3 border-t border-tv-border/50 flex flex-col gap-1.5">
          <!-- Learn More -->
          <div class="border-t border-tv-border/30 mt-2 pt-2">
            <button @click="showLearnMore = !showLearnMore"
                    class="text-xs text-tv-blue hover:text-tv-blue/80 transition-colors cursor-pointer inline-flex items-center gap-1">
              <BaseIcon name="info-circle" />{{ showLearnMore ? 'Hide' : 'Learn more about roll detection' }}
            </button>
            <div v-if="showLearnMore" class="mt-2 text-xs text-tv-muted leading-relaxed">
              <p>A <span class="text-tv-text font-medium">roll</span> is automatically detected when a position is closed and a new one is opened matching on:</p>
              <ul class="list-disc list-inside mt-1 space-y-0.5 ml-2">
                <li>Same account</li>
                <li>Same underlying</li>
                <li>Same type (Call/Put)</li>
                <li>Same day</li>
              </ul>
              <p class="mt-1.5">Whether you're rolling your Covered Calls or legging out and back into a new Iron Condor, the roll is detected.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
