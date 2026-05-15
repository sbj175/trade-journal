import { tickerLogoUrl } from '@/lib/constants'

const cache = new Map()

export function loadTickerLogo(symbol) {
  if (!symbol) return Promise.resolve(null)
  const key = String(symbol).toUpperCase()
  if (cache.has(key)) return cache.get(key)

  const url = tickerLogoUrl(key)
  const promise = new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve(url)
    img.onerror = () => resolve(null)
    img.src = url
  })

  cache.set(key, promise)
  return promise
}
