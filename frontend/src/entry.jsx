import React, { useEffect, useRef, useState } from 'react'
import { CURRENCIES, dayLabel, localToday, money, send, useApi, useDebounced } from './lib.js'
import { Dialog, Field } from './ui.jsx'

/**
 * The entry line: type an entry in plain words, see how it was understood, press Enter to save.
 */
export function EntryLine({ currency, onSaved, onOpenDetails, inputRef }) {
  const [text, setText] = useState('')
  const [parsed, setParsed] = useState(null)
  const [overrides, setOverrides] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const debounced = useDebounced(text, 180)

  useEffect(() => {
    let live = true
    if (!debounced.trim()) { setParsed(null); setOverrides({}); return }
    send('/api/parse', { text: debounced, currency })
      .then((r) => { if (live) setParsed(r) })
      .catch(() => { if (live) setParsed(null) })
    return () => { live = false }
  }, [debounced, currency])

  const entry = parsed ? { ...parsed.entry, ...overrides } : null
  const ready = entry && entry.amount > 0 && entry.category

  const save = async () => {
    if (!ready || saving) return
    setSaving(true)
    setError('')
    try {
      const body = await send('/api/transactions', entry)
      setText('')
      setParsed(null)
      setOverrides({})
      onSaved(body.transaction)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (ready) save()
      else if (entry) onOpenDetails(entry)
    } else if (e.key === 'Enter' && e.shiftKey && entry) {
      e.preventDefault()
      onOpenDetails(entry)
    } else if (e.key === 'Escape') {
      setText('')
    }
  }

  const cycleCategory = () => {
    if (!parsed) return
    const options = [parsed.entry.category, ...(parsed.alternatives || [])].filter(Boolean)
    if (options.length < 2) return onOpenDetails(entry)
    const i = options.indexOf(entry.category)
    setOverrides((o) => ({ ...o, category: options[(i + 1) % options.length] }))
  }

  return (
    <section className="entry" aria-label="Write an entry">
      <label className="entry-label" htmlFor="entry-input">New entry</label>
      <div className="entry-row">
        <input
          id="entry-input"
          ref={inputRef}
          className="entry-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Lunch 250 yesterday"
          autoComplete="off"
          spellCheck="false"
        />
        <button className="btn btn-primary" onClick={() => (ready ? save() : onOpenDetails(entry || {}))} disabled={saving}>
          {saving ? 'Saving' : ready ? 'Save' : 'Add details'}
        </button>
      </div>
      {entry ? (
        <div className="reading" aria-live="polite">
          <button type="button" className={`token token-${entry.type}`} title="Switch between money out and money in"
            onClick={() => setOverrides((o) => ({ ...o, type: entry.type === 'income' ? 'expense' : 'income' }))}>
            {entry.type === 'income' ? 'Money in' : 'Money out'}
          </button>
          <span className={entry.amount ? 'token' : 'token token-missing'}>
            {entry.amount ? money(entry.amount, entry.currency) : 'amount?'}
          </span>
          <button type="button" className={entry.category ? 'token' : 'token token-missing'} onClick={cycleCategory}
            title={parsed?.alternatives?.length ? `Also possible: ${parsed.alternatives.join(', ')}` : 'Choose a category'}>
            {entry.category || 'category?'}
            {parsed?.understood?.category === 'rule' && <span className="token-note">rule</span>}
            {parsed?.understood?.category === 'history' && <span className="token-note">learned</span>}
          </button>
          <span className="token">{dayLabel(entry.date)}</span>
          {entry.account_name && <span className="token">{entry.account_name}</span>}
          <span className="reading-title">“{entry.title}”</span>
          <span className="reading-help">
            {ready ? 'Enter saves. Shift+Enter to edit first.' : 'Add an amount, or press Enter to fill in the rest.'}
          </span>
        </div>
      ) : (
        <p className="entry-hint">
          Write it the way you'd say it: <i>Uber 340</i>, <i>salary 85k on 1 Nov</i>, <i>coffee 4.50 euros</i>, <i>Netflix 649 via HDFC</i>.
        </p>
      )}
      {error && <p className="form-error">{error}</p>}
    </section>
  )
}

/** Full form for adding or editing an entry, with category suggestions learned from history. */
export function EntryDialog({ initial, onClose, onSaved, onDeleted, currency }) {
  const editing = Boolean(initial?.id)
  const [form, setForm] = useState(() => ({
    title: initial?.title || '',
    amount: initial?.amount ?? '',
    type: initial?.type || 'expense',
    category: initial?.category || '',
    date: initial?.date || localToday(),
    currency: initial?.currency || currency,
    exchange_rate: editing ? initial.exchange_rate ?? '' : '',
    account_name: initial?.account_name || 'Main Checking',
    notes: initial?.notes || ''
  }))
  const [categoryTouched, setCategoryTouched] = useState(Boolean(initial?.category))
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [showRate, setShowRate] = useState(Boolean(editing && initial.currency !== 'USD' && initial.currency !== currency))
  const { data: catData } = useApi('/api/categories')
  const accounts = catData?.accounts || ['Main Checking']
  const debouncedTitle = useDebounced(form.title, 250)

  useEffect(() => {
    if (!debouncedTitle.trim()) { setSuggestions([]); return }
    let live = true
    fetch(`/api/suggest?title=${encodeURIComponent(debouncedTitle)}`)
      .then((r) => r.json())
      .then((r) => {
        if (!live) return
        setSuggestions(r.suggestions || [])
        if (!categoryTouched && r.suggestions?.[0]) {
          setForm((f) => ({ ...f, category: r.suggestions[0].category, type: editing ? f.type : (r.type || f.type) }))
        }
      })
      .catch(() => {})
    return () => { live = false }
  }, [debouncedTitle])

  const set = (patch) => setForm((f) => ({ ...f, ...patch }))

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = await send(editing ? `/api/transactions/${initial.id}` : '/api/transactions', form, editing ? 'PUT' : 'POST')
      onSaved(body.transaction, editing)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!window.confirm(`Delete “${initial.title}”? The ledger will be re-sealed.`)) return
    setBusy(true)
    try {
      await send(`/api/transactions/${initial.id}`, undefined, 'DELETE')
      onDeleted(initial)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Dialog title={editing ? 'Edit entry' : 'New entry'} onClose={onClose}
      footer={
        <>
          {editing && <button type="button" className="btn btn-danger-quiet" onClick={remove} disabled={busy}>Delete</button>}
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" form="entry-form" className="btn btn-primary" disabled={busy}>{editing ? 'Save changes' : 'Add entry'}</button>
        </>
      }>
      <form id="entry-form" className="form" onSubmit={submit}>
        {error && <p className="form-error">{error}</p>}
        <div className="segmented" role="radiogroup" aria-label="Direction">
          {[['expense', 'Money out'], ['income', 'Money in']].map(([v, l]) => (
            <button type="button" key={v} role="radio" aria-checked={form.type === v}
              className={form.type === v ? 'seg on' : 'seg'} onClick={() => set({ type: v })}>{l}</button>
          ))}
        </div>
        <Field label="Description">
          <input value={form.title} onChange={(e) => set({ title: e.target.value })} placeholder="Swiggy, Rent, Salary" required />
        </Field>
        <div className="form-row">
          <Field label="Amount" className="grow">
            <input type="number" inputMode="decimal" min="0.01" step="0.01" value={form.amount} onChange={(e) => set({ amount: e.target.value })} required />
          </Field>
          <Field label="Currency">
            <select value={form.currency} onChange={(e) => set({ currency: e.target.value, exchange_rate: '' })}>
              {CURRENCIES.map(([c]) => <option key={c} value={c}>{c}</option>)}
            </select>
          </Field>
          <Field label="Date">
            <input type="date" value={form.date} onChange={(e) => set({ date: e.target.value })} required />
          </Field>
        </div>
        <Field label="Category">
          <input list="category-list" value={form.category}
            onChange={(e) => { setCategoryTouched(true); set({ category: e.target.value }) }} required />
          <datalist id="category-list">
            {(catData?.categories || []).map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>
        {suggestions.length > 0 && (
          <div className="suggest" aria-label="Suggested categories">
            <span className="suggest-label">Suggested</span>
            {suggestions.map((s) => (
              <button type="button" key={s.category} className={form.category === s.category ? 'chip on' : 'chip'}
                onClick={() => { setCategoryTouched(true); set({ category: s.category }) }}>
                {s.category}
              </button>
            ))}
          </div>
        )}
        <div className="form-row">
          <Field label="Account" className="grow">
            <select value={form.account_name} onChange={(e) => set({ account_name: e.target.value })}>
              {(accounts.includes(form.account_name) ? accounts : [...accounts, form.account_name]).map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </Field>
          {form.currency !== 'USD' && (showRate ? (
            <Field label="Rate to USD" hint="leave blank for the standard rate">
              <input type="number" step="any" min="0" value={form.exchange_rate} onChange={(e) => set({ exchange_rate: e.target.value })} placeholder="Standard" />
            </Field>
          ) : (
            <button type="button" className="link-btn align-end" onClick={() => setShowRate(true)}>Use a specific exchange rate</button>
          ))}
        </div>
        <Field label="Notes" hint="optional">
          <textarea rows="2" value={form.notes} onChange={(e) => set({ notes: e.target.value })} />
        </Field>
      </form>
    </Dialog>
  )
}

export function useEntryShortcut(ref) {
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable) return
      if (e.ctrlKey || e.metaKey || e.altKey || document.querySelector('.scrim')) return
      if (e.key === 'n') {
        e.preventDefault()
        ref.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ref])
}
