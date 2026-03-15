import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useQuotesStore = defineStore('quotes', () => {
  // Written by page composables (positions WebSocket), read by toolbar
  const lastQuoteUpdate = ref(null)

  function setLastQuoteUpdate(time) {
    lastQuoteUpdate.value = time
  }

  return { lastQuoteUpdate, setLastQuoteUpdate }
})
