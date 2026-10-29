import React, { useEffect, useRef, useState } from 'react'
import { money, send, storage, store } from './lib.js'
import { EntryDialog } from './entry.jsx'
import Overview from './pages/Overview.jsx'
import Ledger from './pages/Ledger.jsx'
import Budgets from './pages/Budgets.jsx'
import Recurring from './pages/Recurring.jsx'
import Reports from './pages/Reports.jsx'
import Accounts from './pages/Accounts.jsx'
import Currencies from './pages/Currencies.jsx'
import Rules from './pages/Rules.jsx'

const PAGES = [
  ['overview', 'Overview', Overview],
  ['ledger', 'Ledger', Ledger],
  ['budgets', 'Budgets', Budgets],
  ['recurring', 'Recurring', Recurring],
  ['reports', 'Reports', Reports],
  ['accounts', 'Accounts & goals', Accounts],
  ['currencies', 'Currencies', Currencies],
  ['rules', 'Categories & rules', Rules]
]

function currentRoute() {
  const id = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return PAGES.some(([p]) => p === id) ? id : 'overview'
}

export default function App() {
  const [route, setRoute] = useState(currentRoute)
  const [currency, setCurrencyState] = useState(() => storage('vl-currency', 'INR'))
  const [theme, setTheme] = useState(() => storage('vl-theme', 'system'))
  const [privacy, setPrivacy] = useState(() => storage('vl-private', '0') === '1')
  const [refreshKey, setRefreshKey] = useState(0)
  const [entryDialog, setEntryDialog] = useState(null)
  const [toast, setToast] = useState(null)
  const [ledgerStatus, setLedgerStatus] = useState(null)
  const toastTimer = useRef(null)

  const refresh = () => setRefreshKey((k) => k + 1)
  const setCurrency = (c) => { setCurrencyState(c); store('vl-currency', c) }
  const go = (id) => { window.location.hash = `#/${id}` }

  useEffect(() => {
    const onHash = () => { setRoute(currentRoute()); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
    store('vl-theme', theme)
  }, [theme])

  useEffect(() => { store('vl-private', privacy ? '1' : '0') }, [privacy])

  useEffect(() => {
    fetch('/api/audit/verify', { method: 'POST' }).then((r) => r.json()).then(setLedgerStatus).catch(() => setLedgerStatus(null))
  }, [refreshKey])

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable) return
      if (e.ctrlKey || e.metaKey || e.altKey || document.querySelector('.scrim')) return
      if (e.key === 'p') { e.preventDefault(); setPrivacy((p) => !p) }
      const n = Number(e.key)
      if (e.key >= '1' && e.key <= String(PAGES.length) && n) { e.preventDefault(); go(PAGES[n - 1][0]) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const showToast = (message, undo) => {
    clearTimeout(toastTimer.current)
    setToast({ message, undo })
    toastTimer.current = setTimeout(() => setToast(null), 7000)
  }

  const onEntrySaved = (tx, edited) => {
    setEntryDialog(null)
    refresh()
    const amount = money(tx.amount, tx.currency)
    if (edited) return showToast(`Updated ${tx.title}.`)
    showToast(`Added ${tx.title}, ${amount}${tx.type === 'income' ? ' in' : ''} to ${tx.category}.`, async () => {
      await send(`/api/transactions/${tx.id}`, undefined, 'DELETE')
      setToast(null)
      refresh()
    })
  }

  const ctx = {
    currency, setCurrency, refreshKey, refresh, go, showToast,
    openEntry: (initial) => setEntryDialog(initial || {}),
    onEntrySaved
  }
  const Page = PAGES.find(([id]) => id === route)[2]

  return (
    <div className={privacy ? 'shell private' : 'shell'}>
      <a className="skip" href="#main">Skip to content</a>
      <aside className="rail">
        <div className="mark">
          <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
            <rect x="3" y="2.5" width="16" height="17" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M7 2.5v17M10 8h6M10 11.5h6M10 15h4" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <span>VaultLedger</span>
        </div>
        <nav aria-label="Sections">
          {PAGES.map(([id, label], i) => (
            <a key={id} href={`#/${id}`} className={route === id ? 'nav on' : 'nav'} aria-current={route === id ? 'page' : undefined}>
              <span>{label}</span><kbd>{i + 1}</kbd>
            </a>
          ))}
        </nav>
        <div className="rail-foot">
          <div className="rail-controls">
            <label className="rail-control">
              <span>Show amounts in</span>
              <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {['INR', 'USD', 'EUR', 'GBP', 'CAD', 'JPY'].map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
            <label className="rail-control">
              <span>Appearance</span>
              <select value={theme} onChange={(e) => setTheme(e.target.value)}>
                <option value="system">Match system</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </label>
            <label className="rail-check">
              <input type="checkbox" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} />
              <span>Hide amounts <kbd>P</kbd></span>
            </label>
          </div>
          {ledgerStatus && (
            <p className={ledgerStatus.valid ? 'seal ok' : 'seal broken'} title="Each entry is chained to the previous one with SHA-256, so edits made outside VaultLedger are detected.">
              {ledgerStatus.valid
                ? `Ledger sealed, ${ledgerStatus.verified} ${ledgerStatus.verified === 1 ? 'entry' : 'entries'} verified`
                : `Ledger altered outside the app at entry #${ledgerStatus.compromisedId}`}
            </p>
          )}
        </div>
      </aside>

      <main id="main" className="page">
        <Page {...ctx} />
      </main>

      {entryDialog && (
        <EntryDialog initial={entryDialog} currency={currency} onClose={() => setEntryDialog(null)}
          onSaved={onEntrySaved}
          onDeleted={(tx) => { setEntryDialog(null); refresh(); showToast(`Deleted ${tx.title}.`) }} />
      )}

      {toast && (
        <div className="toast" role="status">
          <span>{toast.message}</span>
          {toast.undo && <button className="link-btn" onClick={toast.undo}>Undo</button>}
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setToast(null)}>
            <svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" /></svg>
          </button>
        </div>
      )}
    </div>
  )
}
