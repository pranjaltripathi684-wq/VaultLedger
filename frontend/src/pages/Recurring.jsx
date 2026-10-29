import React, { useState } from 'react'
import { CURRENCIES, dayLabel, localToday, money, send, useApi } from '../lib.js'
import { Dialog, Empty, ErrorNote, Field, Loading, Money, PageHead } from '../ui.jsx'

const CYCLE = { weekly: 'Weekly', monthly: 'Monthly', quarterly: 'Every 3 months', yearly: 'Yearly' }

function when(days, iso) {
  if (days === null || days === undefined) return ''
  if (days < 0) return `${-days} ${days === -1 ? 'day' : 'days'} overdue`
  return dayLabel(iso)
}

export default function Recurring({ currency, refreshKey, refresh, showToast }) {
  const { data, error, reload } = useApi(`/api/recurring?currency=${currency}`, refreshKey)
  const [adding, setAdding] = useState(false)

  if (!data && error) return <><PageHead title="Recurring" /><ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <><PageHead title="Recurring" /><Loading /></>

  const track = async (r) => {
    try {
      await send('/api/subscriptions', {
        name: r.name, amount: r.amount, currency: r.currency, billing_cycle: r.cadence,
        next_due_date: r.next_date, category: r.category
      })
      showToast(`Tracking ${r.name}. It now counts toward bills still due.`)
      refresh()
    } catch (e) {
      showToast(e.message)
    }
  }
  const untrack = async (s) => {
    if (!window.confirm(`Stop tracking ${s.name}?`)) return
    await send(`/api/subscriptions/${s.id}`, undefined, 'DELETE')
    showToast(`Stopped tracking ${s.name}.`)
    refresh()
  }

  const foundBills = data.detected.filter((r) => r.type === 'expense' && !r.tracked)
  const income = data.detected.filter((r) => r.type === 'income')

  return (
    <>
      <PageHead title="Recurring"
        note={data.monthly_out > 0
          ? <>Regular bills come to about <Money value={data.monthly_out} currency={currency} whole /> a month.</>
          : 'Bills and income that repeat on a schedule.'}>
        <button className="btn" onClick={() => setAdding(true)}>Add a bill</button>
      </PageHead>

      <section className="block" aria-labelledby="tracked-h">
        <h2 id="tracked-h" className="block-title">Tracked bills</h2>
        {data.tracked.length ? (
          <table className="plain">
            <thead><tr><th>Name</th><th>Repeats</th><th>Next</th><th className="c-num">Amount</th><th className="c-num">Per month</th><th /></tr></thead>
            <tbody>
              {data.tracked.map((s) => (
                <tr key={s.id}>
                  <td><span className="desc-title">{s.name}</span><span className="desc-meta">{s.category}</span></td>
                  <td>{CYCLE[s.cycle] || s.cycle}</td>
                  <td className={s.days_until < 0 ? 'overdue' : ''}>{when(s.days_until, s.next_date)}</td>
                  <td className="c-num"><Money value={s.display_amount} currency={currency} />{s.currency !== currency && <span className="orig">{money(s.amount, s.currency)}</span>}</td>
                  <td className="c-num"><Money value={s.monthly} currency={currency} whole /></td>
                  <td className="c-act"><button className="link-btn" onClick={() => untrack(s)}>Stop tracking</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="quiet">Nothing tracked yet. Track a bill below and it is counted in your free-to-spend figure before it's paid.</p>}
      </section>

      <section className="block" aria-labelledby="found-h">
        <h2 id="found-h" className="block-title">Found in your ledger</h2>
        {foundBills.length ? (
          <table className="plain">
            <thead><tr><th>Name</th><th>Pattern</th><th>Expected next</th><th className="c-num">Usually</th><th /></tr></thead>
            <tbody>
              {foundBills.map((r) => (
                <tr key={r.key}>
                  <td><span className="desc-title">{r.name}</span><span className="desc-meta">{r.category}</span></td>
                  <td>{CYCLE[r.cadence]}, seen {r.occurrences} times{r.fixed_amount ? '' : ', amount varies'}</td>
                  <td className={r.status === 'missed' ? 'overdue' : ''}>{r.status === 'missed' ? `Missed? Last on ${r.last_date}` : when(r.days_until, r.next_date)}</td>
                  <td className="c-num"><Money value={r.display_amount} currency={currency} /></td>
                  <td className="c-act"><button className="btn" onClick={() => track(r)}>Track</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>No untracked patterns yet. Entries with the same name, a steady schedule and a similar amount show up here after two or three repeats.</Empty>}
      </section>

      {income.length > 0 && (
        <section className="block" aria-labelledby="income-h">
          <h2 id="income-h" className="block-title">Regular income</h2>
          <table className="plain">
            <tbody>
              {income.map((r) => (
                <tr key={r.key}>
                  <td><span className="desc-title">{r.name}</span></td>
                  <td>{CYCLE[r.cadence]}</td>
                  <td className={r.status === 'missed' ? 'overdue' : ''}>{r.status === 'missed' ? `Not seen since ${r.last_date}` : `Next expected ${when(r.days_until, r.next_date)}`}</td>
                  <td className="c-num"><Money value={r.display_amount} currency={currency} tone="in" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {adding && <AddBill currency={currency} onClose={() => setAdding(false)} onSaved={(name) => { setAdding(false); showToast(`Tracking ${name}.`); refresh() }} />}
    </>
  )
}

function AddBill({ currency, onClose, onSaved }) {
  const [form, setForm] = useState({ name: '', amount: '', currency, billing_cycle: 'monthly', next_due_date: localToday(), category: 'Subscriptions' })
  const [error, setError] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    try {
      await send('/api/subscriptions', form)
      onSaved(form.name)
    } catch (err) {
      setError(err.message)
    }
  }
  return (
    <Dialog title="Add a bill" onClose={onClose}
      footer={<><span className="spacer" /><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" type="submit" form="bill-form">Track bill</button></>}>
      <form id="bill-form" className="form" onSubmit={submit}>
        {error && <p className="form-error">{error}</p>}
        <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Rent, Netflix, Gym" required /></Field>
        <div className="form-row">
          <Field label="Amount" className="grow"><input type="number" min="0.01" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} required /></Field>
          <Field label="Currency">
            <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{CURRENCIES.map(([c]) => <option key={c}>{c}</option>)}</select>
          </Field>
        </div>
        <div className="form-row">
          <Field label="Repeats" className="grow">
            <select value={form.billing_cycle} onChange={(e) => setForm({ ...form, billing_cycle: e.target.value })}>
              {Object.entries(CYCLE).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Next due"><input type="date" value={form.next_due_date} onChange={(e) => setForm({ ...form, next_due_date: e.target.value })} required /></Field>
        </div>
        <Field label="Category"><input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
      </form>
    </Dialog>
  )
}
