import React, { useState } from 'react'
import { CURRENCIES, money, send, useApi } from '../lib.js'
import { Empty, ErrorNote, Field, Loading, Money, PaceBar, PageHead } from '../ui.jsx'

const STATUS_TEXT = { over: 'Over', at_risk: 'At risk', on_track: 'On track' }

function roundUp(v) {
  const step = v >= 10000 ? 1000 : v >= 2000 ? 500 : 100
  return Math.ceil(v / step) * step
}

export default function Budgets({ currency, refreshKey, refresh, showToast }) {
  const { data, error, reload } = useApi(`/api/overview?currency=${currency}`, refreshKey)
  const { data: reports } = useApi(`/api/reports?currency=${currency}`, refreshKey)
  const { data: cats } = useApi('/api/categories', refreshKey)
  const [form, setForm] = useState({ category: '', monthly_limit: '', currency })
  const [formError, setFormError] = useState('')

  if (!data && error) return <><PageHead title="Budgets" /><ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <><PageHead title="Budgets" /><Loading /></>

  const save = async (entry) => {
    setFormError('')
    try {
      await send('/api/budgets', entry)
      setForm({ category: '', monthly_limit: '', currency: entry.currency })
      showToast(`Budget for ${entry.category} saved.`)
      refresh()
    } catch (e) {
      setFormError(e.message)
    }
  }

  const remove = async (b) => {
    if (!window.confirm(`Remove the ${b.category} budget?`)) return
    await send(`/api/budgets/${b.id}`, undefined, 'DELETE')
    showToast(`Removed the ${b.category} budget.`)
    refresh()
  }

  // Suggest limits from the last three complete months for categories without a budget
  const budgeted = new Set(data.budgets.map((b) => b.category))
  let suggestions = []
  if (reports && reports.months.length > 1) {
    const complete = reports.months.length - 1
    const from = Math.max(0, complete - 3)
    suggestions = reports.categories
      .filter((c) => !budgeted.has(c.category))
      .map((c) => {
        const slice = c.by_month.slice(from, complete)
        const avg = slice.reduce((s, v) => s + v, 0) / (slice.length || 1)
        return { category: c.category, avg, limit: roundUp(avg * 1.05), months: slice.length }
      })
      .filter((s) => s.avg > 0)
      .slice(0, 4)
  }

  return (
    <>
      <PageHead title="Budgets" note={`Monthly limits for ${data.month_label}. Projections combine your daily pace with bills still due.`} />

      {data.budgets.length ? (
        <ul className="budget-list">
          {data.budgets.map((b) => (
            <li key={b.id} className="budget">
              <div className="budget-top">
                <h2>{b.category}</h2>
                <span className={`status status-${b.status}`}>{STATUS_TEXT[b.status]}</span>
                <span className="budget-nums"><Money value={b.spent} currency={currency} whole /> <span className="of">of</span> <Money value={b.limit} currency={currency} whole /></span>
              </div>
              <PaceBar spent={b.spent} limit={b.limit} projected={b.projected} status={b.status} />
              <div className="budget-foot">
                <p>
                  {b.status === 'over' && <>{money(-b.left, currency, { whole: true })} over the limit. At this pace the month ends near {money(b.projected, currency, { whole: true })}.</>}
                  {b.status === 'at_risk' && <>On pace for {money(b.projected, currency, { whole: true })}, about {money(b.overshoot, currency, { whole: true })} over. Keeping to {money(b.per_day_left, currency, { whole: true })} a day stays within it.</>}
                  {b.status === 'on_track' && <>{money(b.left, currency, { whole: true })} left, about {money(b.per_day_left, currency, { whole: true })} a day for the rest of the month.</>}
                  {b.currency !== currency && <span className="quiet"> Set in {b.currency}.</span>}
                </p>
                <button className="link-btn" onClick={() => remove(b)}>Remove</button>
              </div>
            </li>
          ))}
        </ul>
      ) : <Empty>No budgets yet. Add one below, or start from a suggestion based on what you usually spend.</Empty>}

      <div className="split even">
        <section className="block" aria-labelledby="add-budget">
          <h2 id="add-budget" className="block-title">Add or change a budget</h2>
          <form className="form" onSubmit={(e) => { e.preventDefault(); save(form) }}>
            {formError && <p className="form-error">{formError}</p>}
            <Field label="Category">
              <input list="budget-cats" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} required />
              <datalist id="budget-cats">{(cats?.categories || []).map((c) => <option key={c} value={c} />)}</datalist>
            </Field>
            <div className="form-row">
              <Field label="Monthly limit" className="grow">
                <input type="number" min="1" step="1" value={form.monthly_limit} onChange={(e) => setForm({ ...form, monthly_limit: e.target.value })} required />
              </Field>
              <Field label="Currency">
                <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                  {CURRENCIES.map(([c]) => <option key={c}>{c}</option>)}
                </select>
              </Field>
            </div>
            <div><button className="btn btn-primary" type="submit">Save budget</button></div>
          </form>
        </section>

        <section className="block" aria-labelledby="suggest-budget">
          <h2 id="suggest-budget" className="block-title">Suggested from your spending</h2>
          {suggestions.length ? (
            <ul className="suggest-list">
              {suggestions.map((s) => (
                <li key={s.category}>
                  <div>
                    <span className="suggest-name">{s.category}</span>
                    <span className="quiet">averages {money(s.avg, currency, { whole: true })} a month over the last {s.months} {s.months === 1 ? 'month' : 'months'}</span>
                  </div>
                  <button className="btn" onClick={() => save({ category: s.category, monthly_limit: s.limit, currency })}>
                    Set {money(s.limit, currency, { whole: true })}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="quiet">Suggestions appear once you have a full month of entries in a category without a budget.</p>}
        </section>
      </div>
    </>
  )
}
