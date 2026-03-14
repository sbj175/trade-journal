/**
 * Quote management: WebSocket streaming, cached quote loading, and P&L helpers.
 * Composable that takes Auth and a reactive items ref for symbol collection.
 */
import { ref } from 'vue'

export function useEquityQuotes(Auth, filteredItems) {
  const underlyingQuotes = ref({})
  const quoteUpdateCounter = ref(0)
  const liveQuotesActive = ref(false)
  const lastQuoteUpdate = ref(null)

  let ws = null

  // --- Symbol collection ---

  function collectSymbols() {
    return [...new Set(filteredItems.value.map(i => i.underlying).filter(Boolean))]
  }

  // --- Quote accessors ---

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

  // --- Data loading ---

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

  // --- WebSocket ---

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

  function closeWebSocket() {
    if (ws) { ws.close(); ws = null }
  }

  return {
    // State
    underlyingQuotes, quoteUpdateCounter, liveQuotesActive, lastQuoteUpdate,
    // Quote accessors
    getQuote, getQuotePrice, getMarketValue, getUnrealizedPnL, getPnLPercent,
    getLotMarketValue, getLotPnL,
    // Data loading
    loadCachedQuotes, initializeWebSocket, closeWebSocket,
  }
}
