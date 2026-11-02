// Colours, number formats and file downloads shared by the statistics page's charts.

// Categorical colours in fixed order; a series keeps its slot whatever else is shown.
export const SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']

export const formatInt = (n: number) => n.toLocaleString('en')
export const formatCompact = (n: number) =>
  new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: n >= 1e6 ? 1 : 0 }).format(n)
export const formatPct = (n: number) => `${n.toFixed(n < 10 ? 1 : 0)}%`

export function downloadFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
