import { useEffect, useRef, useState } from 'react'

export const CURRENCIES = [
  ['INR', '₹', 'Indian rupee'],
  ['USD', '$', 'US dollar'],
  ['EUR', '€', 'Euro'],
  ['GBP', '£', 'British pound'],
  ['CAD', 'C$', 'Canadian dollar'],
  ['JPY', '¥', 'Japanese yen']
]

const formatters = new Map()
function formatter(currency, digits) {
  const key = `${currency}:${digits}`
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }))
  }
  return formatters.get(key)
}

/** Money with the right grouping per currency (₹1,23,456 for INR). `whole` drops paise/cents. */
export function money(value, currency = 'INR', { whole = false, sign = false } = {}) {
  const digits = currency === 'JPY' || whole ? 0 : 2
  let v = Number(value) || 0
  if (Math.abs(v) < (digits ? 0.005 : 0.5)) v = 0
  const text = formatter(currency, digits).format(Math.abs(v))
  if (v < 0) return `−${text}`
  if (sign && v > 0) return `+${text}`
  return text
}

export function localToday() {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

export function parseISO(iso) {
  const [y, m, d] = String(iso).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function dayLabel(iso, todayIso = localToday()) {
  const d = parseISO(iso)
  const t = parseISO(todayIso)
  const diff = Math.round((t - d) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  if (diff === -1) return 'Tomorrow'
  const sameYear = d.getFullYear() === t.getFullYear()
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric' })
}

export function shortDate(iso) {
  return parseISO(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

export function monthLabel(key) {
  const [y, m] = key.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

export function useApi(path, refreshKey = 0) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const requestId = useRef(0)
  const load = async () => {
    const id = ++requestId.current
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const response = await fetch(path)
      if (!response.ok) throw new Error(`The server answered ${response.status} for ${path}.`)
      const body = await response.json()
      if (id === requestId.current) setState({ loading: false, data: body, error: null })
    } catch (error) {
      if (id === requestId.current) {
        setState((s) => ({ loading: false, data: s.data, error: error.message === 'Failed to fetch' ? 'VaultLedger is not running. Start it again and retry.' : error.message }))
      }
    }
  }
  useEffect(() => { load() }, [path, refreshKey])
  return { ...state, reload: load }
}

export async function send(url, body, method = 'POST') {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try { message = (await response.json()).error || message } catch (_) { /* empty body */ }
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json().catch(() => null)
}

export function useDebounced(value, delay = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

export function storage(key, fallback) {
  try {
    const v = window.localStorage.getItem(key)
    return v === null ? fallback : v
  } catch (_) {
    return fallback
  }
}

export function store(key, value) {
  try { window.localStorage.setItem(key, value) } catch (_) { /* private mode */ }
}
