/**
 * ApexCharts rendering and lifecycle management.
 */
import { formatNumber } from '@/lib/formatters'
import { chart as C } from '@/lib/design-tokens'
import { calcThetaProjection, calcScenarios, shortNumber } from '@/lib/riskCalculations'

export function useRiskCharts(deps) {
  const { underlyingGroups, enrichedPositions } = deps

  // Internal (non-reactive)
  const charts = {}
  let chartTimer = null

  // ==================== LIFECYCLE ====================
  async function ensureApexCharts() {
    if (window.ApexCharts) return
    return new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = 'https://cdn.jsdelivr.net/npm/apexcharts'
      s.onload = resolve
      s.onerror = reject
      document.head.appendChild(s)
    })
  }

  function destroyCharts() {
    if (chartTimer) {
      clearTimeout(chartTimer)
      chartTimer = null
    }
    Object.values(charts).forEach(c => c.destroy?.())
  }

  function debouncedUpdateCharts() {
    if (chartTimer) return
    chartTimer = setTimeout(() => {
      chartTimer = null
      renderAllCharts()
    }, 2000)
  }

  // ==================== RENDER ALL ====================
  function renderAllCharts() {
    if (underlyingGroups.value.length === 0) return
    renderDeltaChart()
    renderThetaChart()
    renderTreemapChart()
    renderScenarioChart()
  }

  // ==================== DELTA CHART ====================
  function renderDeltaChart() {
    const groups = [...underlyingGroups.value].sort((a, b) => Math.abs(b.deltaDollars) - Math.abs(a.deltaDollars)).slice(0, 15)
    const categories = groups.map(g => g.underlying)
    const values = groups.map(g => Math.round(g.deltaDollars))

    const options = {
      chart: {
        type: 'bar', height: 280, background: 'transparent', toolbar: { show: false },
        animations: { enabled: true, easing: 'easeinout', speed: 400 },
      },
      series: [{ name: 'Delta $', data: values }],
      plotOptions: {
        bar: {
          horizontal: true, borderRadius: 3, barHeight: '70%',
          colors: { ranges: [{ from: -9999999, to: -0.01, color: C.red }, { from: 0, to: 9999999, color: C.green }] },
        },
      },
      xaxis: {
        categories,
        labels: { style: { colors: C.muted, fontSize: '11px' }, formatter: v => '$' + shortNumber(v) },
      },
      yaxis: { labels: { style: { colors: C.text, fontSize: '12px', fontWeight: 600 } } },
      grid: { borderColor: C.grid, xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } } },
      tooltip: {
        theme: 'dark',
        y: { formatter: v => (v >= 0 ? '+$' : '-$') + formatNumber(Math.abs(v)) + ' delta exposure' },
      },
      dataLabels: { enabled: false },
    }

    if (charts.delta) {
      charts.delta.updateOptions(options, true, true)
    } else {
      charts.delta = new window.ApexCharts(document.querySelector('#chart-delta'), options)
      charts.delta.render()
    }
  }

  // ==================== THETA CHART ====================
  function renderThetaChart() {
    const projection = calcThetaProjection(enrichedPositions.value)
    const options = {
      chart: {
        type: 'area', height: 280, background: 'transparent', toolbar: { show: false },
        animations: { enabled: true, easing: 'easeinout', speed: 400 },
      },
      series: [{ name: 'Cumulative Theta', data: projection.cumulative }],
      xaxis: {
        categories: projection.days,
        labels: {
          style: { colors: C.muted, fontSize: '11px' },
          formatter: (v, i) => {
            if (i === 0) return 'Today'
            if (i % 7 === 0) return 'Day ' + v
            return ''
          },
        },
        tickAmount: 7,
      },
      yaxis: {
        labels: { style: { colors: C.muted, fontSize: '11px' }, formatter: v => '$' + shortNumber(v) },
      },
      stroke: { curve: 'smooth', width: 2 },
      fill: {
        type: 'gradient',
        gradient: {
          shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05,
          stops: [0, 90, 100],
          colorStops: [
            { offset: 0, color: C.green, opacity: 0.4 },
            { offset: 100, color: C.green, opacity: 0.05 },
          ],
        },
      },
      colors: [C.green],
      grid: { borderColor: C.grid },
      tooltip: {
        theme: 'dark',
        x: { formatter: (v) => 'Day ' + v },
        y: { formatter: v => '+$' + formatNumber(v) + ' projected income' },
      },
      annotations: {
        xaxis: projection.expirationMarkers.map(m => ({
          x: m.day,
          borderColor: C.muted,
          strokeDashArray: 4,
          label: {
            text: m.label,
            style: { color: C.text, background: C.grid, fontSize: '10px' },
            borderColor: C.grid, orientation: 'horizontal', offsetY: -5,
          },
        })),
      },
      dataLabels: { enabled: false },
    }

    if (charts.theta) {
      charts.theta.updateOptions(options, true, true)
    } else {
      charts.theta = new window.ApexCharts(document.querySelector('#chart-theta'), options)
      charts.theta.render()
    }
  }

  // ==================== TREEMAP CHART ====================
  function renderTreemapChart() {
    const groups = underlyingGroups.value.filter(g => g.maxRisk > 0)
    const data = groups.map(g => ({
      x: g.underlying + ' ($' + shortNumber(g.maxRisk) + ')',
      y: Math.round(g.maxRisk),
      fillColor: g.unrealizedPnl >= 0 ? C.green : C.red,
    }))

    const options = {
      chart: {
        type: 'treemap', height: 280, background: 'transparent', toolbar: { show: false },
        animations: { enabled: true, speed: 400 },
      },
      series: [{ data }],
      plotOptions: {
        treemap: {
          distributed: true, enableShades: true, shadeIntensity: 0.3,
          colorScale: { ranges: [] },
        },
      },
      legend: { show: false },
      tooltip: {
        theme: 'dark',
        y: {
          formatter: (v, { dataPointIndex }) => {
            const g = groups[dataPointIndex]
            if (!g) return '$' + formatNumber(v)
            return '$' + formatNumber(v) + ' max risk | P&L: ' +
              (g.unrealizedPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(g.unrealizedPnl))
          },
        },
      },
      dataLabels: {
        enabled: true,
        style: { fontSize: '13px', fontWeight: 600, colors: [C.white] },
        formatter: (text, op) => [text.split(' ')[0], '$' + shortNumber(op.value)],
        offsetY: -2,
      },
    }

    if (charts.treemap) {
      charts.treemap.updateOptions(options, true, true)
    } else {
      charts.treemap = new window.ApexCharts(document.querySelector('#chart-treemap'), options)
      charts.treemap.render()
    }
  }

  // ==================== SCENARIO CHART ====================
  function renderScenarioChart() {
    const scenarios = calcScenarios(enrichedPositions.value)
    const options = {
      chart: {
        type: 'area', height: 280, background: 'transparent', toolbar: { show: false },
        animations: { enabled: true, easing: 'easeinout', speed: 400 },
      },
      series: [{ name: 'Portfolio P&L Change', data: scenarios.pnl }],
      xaxis: {
        categories: scenarios.labels,
        labels: { style: { colors: C.muted, fontSize: '11px' } },
        axisBorder: { show: false },
      },
      yaxis: {
        labels: {
          style: { colors: C.muted, fontSize: '11px' },
          formatter: v => (v >= 0 ? '+$' : '-$') + shortNumber(Math.abs(v)),
        },
      },
      stroke: { curve: 'smooth', width: 3 },
      fill: {
        type: 'gradient',
        gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05, stops: [0, 90, 100] },
      },
      colors: [C.blue],
      grid: { borderColor: C.grid },
      annotations: {
        yaxis: [{
          y: 0, borderColor: C.muted, strokeDashArray: 3,
          label: { text: 'Break Even', style: { color: C.muted, background: 'transparent', fontSize: '10px' } },
        }],
        xaxis: [{
          x: '0%', borderColor: C.muted, strokeDashArray: 3,
          label: { text: 'Current', style: { color: C.text, background: C.grid, fontSize: '10px' }, borderColor: C.grid },
        }],
      },
      tooltip: {
        theme: 'dark',
        y: { formatter: v => (v >= 0 ? '+$' : '-$') + formatNumber(Math.abs(v)) },
      },
      dataLabels: { enabled: false },
    }

    if (charts.scenario) {
      charts.scenario.updateOptions(options, true, true)
    } else {
      charts.scenario = new window.ApexCharts(document.querySelector('#chart-scenario'), options)
      charts.scenario.render()
    }
  }

  return {
    ensureApexCharts, destroyCharts, debouncedUpdateCharts, renderAllCharts,
  }
}
