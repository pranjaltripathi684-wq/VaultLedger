import React, { useEffect, useMemo, useRef, useState } from 'react'
import { dayLabel, money, monthLabel, send, useApi } from '../lib.js'
import { Empty, ErrorNote, Loading, Money, PageHead } from '../ui.jsx'

function initialFlagged() {
  return /flagged=1/.test(window.location.hash)
}

export default function Ledger({ currency, refreshKey, refresh, openEntry, showToast }) {
  const { data, error, reload } = useApi(`/api/ledger?currency=${currency}`, refreshKey)
  const [query, setQuery] = useState('')
  const [month, setMonth] = useState('all')
  const [direction, setDirection] = useState('all')
  const [category, setCategory] = useState('all')
  const [flaggedOnly, setFlaggedOnly] = useState(initialFlagged)
  const [selected, setSelected] = useState(() => new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const searchRef = useRef(null)

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (['input', 'textarea', 'select'].includes(tag) || document.querySelector('.scrim')) return
      if (e.key === '/') { e.preventDefault(); searchRef.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Changing what is visible clears the selection, so bulk actions never touch hidden rows
  useEffect(() => { setSelected(new Set()) }, [query, month, direction, category, flaggedOnly, refreshKey])

  const months = useMemo(() => {
    if (!data) return []
    return [...new Set(data.transactions.map((t) => t.date.slice(0, 7)))]
  }, [data])

  const rows = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    return data.transactions.filter((t) => {
      if (month !== 'all' && !t.date.startsWith(month)) return false
      if (direction !== 'all' && t.type !== direction) return false
      if (category !== 'all' && t.category !== category) return false
      if (flaggedOnly && !t.flag) return false
      if (q && !`${t.title} ${t.category} ${t.notes || ''} ${t.account_name || ''} ${t.amount}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [data, query, month, direction, category, flaggedOnly])

  const groups = useMemo(() => {
    const out = []
    for (const t of rows) {
      const last = out[out.length - 1]
      if (last && last.date === t.date) last.items.push(t)
      else out.push({ date: t.date, items: [t] })
    }
    return out
  }, [rows])

  const totals = useMemo(() => rows.reduce((acc, t) => {
    acc[t.type] += t.display_amount
    return acc
  }, { income: 0, expense: 0 }), [rows])

  if (!data && error) return <><PageHead title="Ledger" /><ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <><PageHead title="Ledger" /><Loading /></>

  const toggle = (id) => setSelected((s) => {
    const n = new Set(s)
    n.has(id) ? n.delete(id) : n.add(id)
    return n
  })
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id))
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))

  const bulk = async (action) => {
    const ids = [...selected]
    if (action === 'delete' && !window.confirm(`Delete ${ids.length} ${ids.length === 1 ? 'entry' : 'entries'}? The ledger will be re-sealed.`)) return
    if (action === 'recategorize' && !bulkCategory.trim()) return
    try {
      await send('/api/transactions/bulk', { action, ids, new_category: bulkCategory.trim() })
      showToast(action === 'delete' ? `Deleted ${ids.length} entries.` : `Moved ${ids.length} entries to ${bulkCategory.trim()}.`)
      setBulkCategory('')
      refresh()
    } catch (e) {
      showToast(e.message)
    }
  }

  const filtersActive = query || month !== 'all' || direction !== 'all' || category !== 'all' || flaggedOnly

  return (
    <>
      <PageHead title="Ledger" note={`${data.transactions.length} entries, newest first. The balance column is the running total after each entry.`}>
        <a className="btn" href="/export/csv">Export CSV</a>
        <button className="btn btn-primary" onClick={() => openEntry({})}>New entry</button>
      </PageHead>

      <div className="filters" role="search">
        <input ref={searchRef} className="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="Search entries" aria-label="Search entries (press / to focus)" />
        <select value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month">
          <option value="all">All months</option>
          {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
        <select value={direction} onChange={(e) => setDirection(e.target.value)} aria-label="Direction">
          <option value="all">In and out</option>
          <option value="expense">Money out</option>
          <option value="income">Money in</option>
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="all">All categories</option>
          {data.categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label className="check">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
          Flagged only{data.anomalies.length ? ` (${data.anomalies.length})` : ''}
        </label>
        {filtersActive && (
          <button className="link-btn" onClick={() => { setQuery(''); setMonth('all'); setDirection('all'); setCategory('all'); setFlaggedOnly(false) }}>
            Clear filters
          </button>
        )}
      </div>

      {flaggedOnly && data.anomalies.length > 0 && (
        <ul className="review-list" aria-label="Flagged for review">
          {data.anomalies.map((a, i) => (
            <li key={i}>
              <span>{a.message}</span>
              <button className="link-btn" onClick={async () => {
                await send(`/api/anomalies/${a.transaction_id}/dismiss`)
                showToast('Marked as fine. It will not be flagged again.')
                refresh()
              }}>Mark as fine</button>
            </li>
          ))}
        </ul>
      )}

      {filtersActive && rows.length > 0 && (
        <p className="filter-sum">
          {rows.length} {rows.length === 1 ? 'entry' : 'entries'}: <Money value={totals.expense} currency={currency} /> out, <Money value={totals.income} currency={currency} /> in
        </p>
      )}

      {rows.length === 0 ? (
        <Empty>{data.transactions.length ? 'No entries match these filters.' : 'No entries yet. Add one from the Overview or with New entry.'}</Empty>
      ) : (
        <div className="sheet">
          <table className="ledger">
            <thead>
              <tr>
                <th className="c-check"><input type="checkbox" aria-label="Select all shown" checked={allSelected} onChange={toggleAll} /></th>
                <th className="c-desc">Description</th>
                <th className="c-cat">Category</th>
                <th className="c-num">Out</th>
                <th className="c-num">In</th>
                <th className="c-num c-bal">Balance</th>
              </tr>
            </thead>
            {groups.map((g) => {
              const net = g.items.reduce((s, t) => s + (t.type === 'income' ? t.display_amount : -t.display_amount), 0)
              return (
                <tbody key={g.date}>
                  <tr className="day-row">
                    <th colSpan="3" scope="rowgroup">{dayLabel(g.date)}</th>
                    <td colSpan="3" className="day-net"><Money value={net} currency={currency} sign tone="auto" /></td>
                  </tr>
                  {g.items.map((t) => (
                    <tr key={t.id} className={selected.has(t.id) ? 'tx-row selected' : 'tx-row'}>
                      <td className="c-check"><input type="checkbox" aria-label={`Select ${t.title}`} checked={selected.has(t.id)} onChange={() => toggle(t.id)} /></td>
                      <td className="c-desc">
                        <button className="row-open" onClick={() => openEntry(t)}>{t.title}</button>
                        <span className="desc-meta">
                          {t.account_name !== 'Main Checking' && t.account_name}
                          {t.notes && <span className="desc-notes">{t.notes}</span>}
                          {t.flag && <em className="flag">{t.flag}</em>}
                        </span>
                      </td>
                      <td className="c-cat">{t.category}</td>
                      <td className="c-num">
                        {t.type === 'expense' && <>
                          <Money value={t.display_amount} currency={currency} tone="out" />
                          {t.currency !== currency && <span className="orig">{money(t.amount, t.currency)}</span>}
                        </>}
                      </td>
                      <td className="c-num">
                        {t.type === 'income' && <>
                          <Money value={t.display_amount} currency={currency} tone="in" />
                          {t.currency !== currency && <span className="orig">{money(t.amount, t.currency)}</span>}
                        </>}
                      </td>
                      <td className="c-num c-bal"><Money value={t.running_balance} currency={currency} /></td>
                    </tr>
                  ))}
                </tbody>
              )
            })}
          </table>
        </div>
      )}

      {selected.size > 0 && (
        <div className="bulkbar" role="region" aria-label="Selected entries">
          <span>{selected.size} selected</span>
          <input list="bulk-cats" value={bulkCategory} onChange={(e) => setBulkCategory(e.target.value)} placeholder="Move to category" aria-label="New category" />
          <datalist id="bulk-cats">{data.categories.map((c) => <option key={c} value={c} />)}</datalist>
          <button className="btn" onClick={() => bulk('recategorize')} disabled={!bulkCategory.trim()}>Move</button>
          <button className="btn btn-danger-quiet" onClick={() => bulk('delete')}>Delete</button>
          <button className="link-btn" onClick={() => setSelected(new Set())}>Cancel</button>
        </div>
      )}
    </>
  )
}
