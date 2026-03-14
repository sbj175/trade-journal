/**
 * Lot grouping, sorting, close status, and equity aggregation.
 * All functions are pure — no reactive state dependencies.
 */
import { formatDate } from '@/lib/formatters'

export function sortedLots(group) {
  return (group.lots || []).slice().sort((a, b) => {
    const aOpen = a.status !== 'CLOSED' ? 0 : 1
    const bOpen = b.status !== 'CLOSED' ? 0 : 1
    if (aOpen !== bOpen) return aOpen - bOpen

    if (aOpen === 0) {
      // Open/partial: expiration asc, strike desc, entry date desc
      const aExp = a.expiration || ''
      const bExp = b.expiration || ''
      if (aExp !== bExp) return aExp.localeCompare(bExp)
      if ((a.strike || 0) !== (b.strike || 0)) return (b.strike || 0) - (a.strike || 0)
      return (b.entry_date || '').localeCompare(a.entry_date || '')
    }

    // Closed: expiration desc, strike desc, entry date desc
    const aExp = a.expiration || ''
    const bExp = b.expiration || ''
    if (aExp !== bExp) return bExp.localeCompare(aExp)
    if ((a.strike || 0) !== (b.strike || 0)) return (b.strike || 0) - (a.strike || 0)
    return (b.entry_date || '').localeCompare(a.entry_date || '')
  })
}

export function sortedOptionLots(group) {
  return sortedLots(group).filter(l => l.instrument_type !== 'EQUITY' || l.status === 'CLOSED')
}

export function groupedOptionLegs(group) {
  const lots = sortedOptionLots(group)
  const map = new Map()

  for (const lot of lots) {
    const closings = lot.closings || []
    const isOpen = lot.status !== 'CLOSED'

    if (isOpen || closings.length === 0) {
      const disposition = isOpen ? 'OPEN' : 'CLOSED'
      _addToLegMap(map, lot, disposition, isOpen ? (lot.remaining_quantity ?? lot.quantity) : lot.quantity, closings)
    } else {
      const byType = {}
      for (const c of closings) {
        const dtype = c.closing_type || 'MANUAL'
        if (!byType[dtype]) byType[dtype] = []
        byType[dtype].push(c)
      }
      const types = Object.keys(byType)
      if (types.length === 1) {
        _addToLegMap(map, lot, types[0], lot.quantity, closings)
      } else {
        for (const [dtype, dClosings] of Object.entries(byType)) {
          const splitQty = dClosings.reduce((s, c) => s + c.quantity_closed, 0)
          const signedQty = lot.quantity > 0 ? splitQty : -splitQty
          _addToLegMap(map, lot, dtype, signedQty, dClosings)
        }
      }
    }
  }

  const result = [...map.values()]
  for (const leg of result) {
    const multiplier = leg.option_type ? 100 : 1
    const originalQty = Math.abs(leg.totalQuantity)
    leg.avgEntryPrice = originalQty > 0 ? Math.abs(leg.totalCostBasis) / originalQty / multiplier : 0
    leg.expired = leg.disposition === 'EXPIRATION'
    leg.exercised = leg.disposition === 'EXERCISE'
    leg.assigned = leg.disposition === 'ASSIGNMENT'
    if (leg.expired || leg.exercised || leg.assigned) {
      leg.avgClosePrice = null
    } else if (leg.totalProceeds && leg.status === 'CLOSED') {
      leg.avgClosePrice = originalQty > 0 ? Math.abs(leg.totalProceeds) / originalQty / multiplier : 0
    } else {
      leg.avgClosePrice = null
    }
    leg.closeStatus = _buildCloseStatus(leg)
  }

  const dispOrder = { OPEN: 0, MANUAL: 1, CLOSED: 1, EXERCISE: 2, ASSIGNMENT: 3, EXPIRATION: 4 }
  result.sort((a, b) => {
    const aOpen = a.status !== 'CLOSED' ? 0 : 1
    const bOpen = b.status !== 'CLOSED' ? 0 : 1
    if (aOpen !== bOpen) return aOpen - bOpen
    const aExp = a.expiration || ''
    const bExp = b.expiration || ''
    if (aOpen === 0) {
      if (aExp !== bExp) return aExp.localeCompare(bExp)
      return (b.strike || 0) - (a.strike || 0)
    }
    if (aExp !== bExp) return bExp.localeCompare(aExp)
    if ((a.strike || 0) !== (b.strike || 0)) return (b.strike || 0) - (a.strike || 0)
    return (dispOrder[a.disposition] || 9) - (dispOrder[b.disposition] || 9)
  })

  return result
}

function _addToLegMap(map, lot, disposition, qty, closings) {
  const key = `${lot.expiration || '_'}|${lot.strike || '_'}|${lot.option_type || '_'}|${lot.instrument_type || '_'}|${disposition}`
  if (!map.has(key)) {
    map.set(key, {
      key,
      expiration: lot.expiration,
      strike: lot.strike,
      option_type: lot.option_type,
      instrument_type: lot.instrument_type,
      disposition,
      status: disposition === 'OPEN' ? 'OPEN' : 'CLOSED',
      totalQuantity: 0,
      totalCostBasis: 0,
      totalProceeds: 0,
      totalRealized: 0,
      totalFees: 0,
      entryDate: null,
      closeDate: null,
      lotCount: 0,
      lots: [],
      _closings: [],
    })
  }
  const agg = map.get(key)
  agg.totalQuantity += qty
  const multiplier = lot.option_type ? 100 : 1
  const totalLotQty = Math.abs(lot.quantity)
  const splitQty = Math.abs(qty)
  const proportion = totalLotQty > 0 ? splitQty / totalLotQty : 1
  agg.totalCostBasis += (lot.cost_basis || 0) * proportion
  agg.totalFees += (lot.opening_fees || 0) * proportion
  for (const c of closings) {
    agg.totalProceeds += c.quantity_closed * (c.closing_price || 0) * multiplier
    agg.totalRealized += c.realized_pnl || 0
    agg.totalFees += c.fees || 0
  }
  if (!agg.entryDate || (lot.entry_date && lot.entry_date < agg.entryDate)) {
    agg.entryDate = lot.entry_date
  }
  for (const c of closings) {
    if (c.closing_date && (!agg.closeDate || c.closing_date > agg.closeDate)) {
      agg.closeDate = c.closing_date
    }
  }
  agg.lotCount++
  agg.lots.push(lot)
  agg._closings.push(...closings)
}

function _buildCloseStatus(leg) {
  if (leg.status !== 'CLOSED' || leg._closings.length === 0) return null
  const disp = leg.disposition
  const totalQty = leg._closings.reduce((s, c) => s + c.quantity_closed, 0)
  let latestDate = null
  for (const c of leg._closings) {
    if (c.closing_date && (!latestDate || c.closing_date > latestDate)) {
      latestDate = c.closing_date
    }
  }
  const dateStr = latestDate ? formatDate(latestDate) : ''
  const labels = { MANUAL: 'Closed', EXPIRATION: 'Expired', EXERCISE: 'Exercised', ASSIGNMENT: 'Assigned' }
  const label = labels[disp] || 'Closed'
  return `${label} (${totalQty}, ${dateStr})`
}

export function groupInitialPremium(group) {
  return (group.lots || []).reduce((s, l) => s + (l.cost_basis || 0), 0)
}

export function openEquityLots(group) {
  return (group.lots || []).filter(l => l.instrument_type === 'EQUITY' && l.status !== 'CLOSED')
    .sort((a, b) => (b.entry_date || '').localeCompare(a.entry_date || ''))
}

export function equityAggregate(group) {
  const lots = openEquityLots(group)
  if (lots.length === 0) return null
  const totalQty = lots.reduce((s, l) => s + (l.remaining_quantity ?? l.quantity), 0)
  const totalCost = lots.reduce((s, l) => s + (l.cost_basis || 0), 0)
  return {
    quantity: totalQty,
    avgPrice: totalQty !== 0 ? Math.abs(totalCost) / Math.abs(totalQty) : 0,
    costBasis: totalCost,
    lotCount: lots.length,
  }
}

export function lotCloseDate(lot) {
  const closings = lot.closings || []
  if (closings.length === 0) return null
  return closings.reduce((latest, c) =>
    !latest || (c.closing_date > latest) ? c.closing_date : latest, null)
}

export function lotCloseSummary(lot) {
  const closings = lot.closings || []
  if (closings.length === 0) return null
  const multiplier = lot.option_type ? 100 : 1
  let totalQty = 0, totalValue = 0
  for (const c of closings) {
    totalQty += c.quantity_closed
    totalValue += c.quantity_closed * (c.closing_price || 0) * multiplier
  }
  return {
    avgPrice: totalQty > 0 ? totalValue / totalQty / multiplier : 0,
    proceeds: totalValue,
  }
}
