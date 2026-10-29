import React, { useRef } from 'react'
import { dayLabel, money, shortDate, useApi } from '../lib.js'
import { EntryLine, useEntryShortcut } from '../entry.jsx'
import { Empty, ErrorNote, Loading, Money, PaceBar, SpendCurve } from '../ui.jsx'

const STATUS_TEXT = { over: 'Over', at_risk: 'At risk', on_track: 'On track' }

export default function Overview({ currency, refreshKey, refresh, go, openEntry, onEntrySaved }) {
  const { data, error, reload } = useApi(`/api/overview?currency=${currency}`, refreshKey)
  const entryRef = useRef(null)
  useEntryShortcut(entryRef)

  const head = data ? (
    <header className="page-head">
      <div>
        <h1>{data.month_label}</h1>
        <p className="page-note">Day {data.day} of {data.days_in_month}</p>
      </div>
    </header>
  ) : <header className="page-head"><div><h1>Overview</h1></div></header>

  const entry = <EntryLine currency={currency} inputRef={entryRef} onSaved={(tx) => onEntrySaved(tx, false)} onOpenDetails={openEntry} />

  if (!data && error) return <>{head}{entry}<ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <>{head}<Loading /></>

  if (!data.count) {
    return (
      <>
        {head}
        {entry}
        <Empty>Your ledger is empty. Write your first entry above, for example <i>Salary 85000 on 1 Nov</i>.</Empty>
      </>
    )
  }

  const t = data.totals
  const vsPrev = t.spent - t.prev_same_day
  const limitTotal = data.budgets.reduce((s, b) => s + b.limit, 0)
  const daysForSplit = data.days_left + 1

  return (
    <>
      {head}
      {entry}

      <section className="figures" aria-label="This month">
        <div className="figure">
          <h2>Spent so far</h2>
          <Money value={t.spent} currency={currency} whole className="figure-value" />
          <p>
            {t.prev_same_day > 0
              ? <>{money(Math.abs(vsPrev), currency, { whole: true })} {vsPrev >= 0 ? 'more' : 'less'} than by day {data.day} of {data.prev_month_label}</>
              : <>Nothing recorded for {data.prev_month_label} to compare with</>}
          </p>
        </div>
        <div className="figure">
          <h2>Free to spend</h2>
          <Money value={data.safe.per_day} currency={currency} whole className="figure-value" />
          <p>
            a day for the next {daysForSplit} {daysForSplit === 1 ? 'day' : 'days'}
            {data.safe.basis === 'income'
              ? <>, from {data.safe.income_is_typical ? 'your usual monthly income of ' : 'income of '}{money(data.safe.income_basis, currency, { whole: true })} less spending{t.committed > 0 ? ` and ${money(t.committed, currency, { whole: true })} of bills still due` : ''}</>
              : <>, based on your balance{t.committed > 0 ? ' less bills still due' : ''}</>}
          </p>
        </div>
        <div className="figure">
          <h2>Month-end estimate</h2>
          <Money value={t.projected} currency={currency} whole className="figure-value" />
          <p>{t.prev_total > 0 ? <>{data.prev_month_label} closed at {money(t.prev_total, currency, { whole: true })}</> : 'Based on your pace and known bills'}</p>
        </div>
      </section>

      <div className="split">
        <section className="block" aria-labelledby="curve-h">
          <h2 id="curve-h" className="block-title">Spending through the month</h2>
          <SpendCurve curves={data.curves} daysInMonth={data.days_in_month} day={data.day} currency={currency}
            limitTotal={limitTotal} prevLabel={data.prev_month_label} />
        </section>

        <section className="block notes" aria-labelledby="notes-h">
          <h2 id="notes-h" className="block-title">Notes</h2>
          {data.insights.length ? (
            <ul className="note-list">
              {data.insights.map((n, i) => (
                <li key={i} className={`note note-${n.tone}`}>
                  <p className="note-title">{n.title}</p>
                  <p className="note-body">{n.body}</p>
                  {n.action === 'recurring' && <button className="link-btn" onClick={() => go('recurring')}>Review recurring</button>}
                  {n.action === 'review' && <button className="link-btn" onClick={() => go('ledger?flagged=1')}>Show flagged entries</button>}
                </li>
              ))}
            </ul>
          ) : <p className="quiet">Nothing stands out this month.</p>}
        </section>
      </div>

      <div className="split even">
        <section className="block" aria-labelledby="budgets-h">
          <div className="block-head">
            <h2 id="budgets-h" className="block-title">Budgets</h2>
            <button className="link-btn" onClick={() => go('budgets')}>Manage</button>
          </div>
          {data.budgets.length ? (
            <ul className="pace-list">
              {data.budgets.map((b) => (
                <li key={b.id}>
                  <div className="pace-row">
                    <span className="pace-name">{b.category}</span>
                    <span className={`status status-${b.status}`}>{STATUS_TEXT[b.status]}</span>
                    <span className="pace-nums"><Money value={b.spent} currency={currency} whole /> of <Money value={b.limit} currency={currency} whole /></span>
                  </div>
                  <PaceBar spent={b.spent} limit={b.limit} projected={b.projected} status={b.status} />
                </li>
              ))}
            </ul>
          ) : (
            <Empty action={<button className="btn" onClick={() => go('budgets')}>Set a budget</button>}>
              Budgets turn the month-end estimate into a per-category warning.
            </Empty>
          )}
        </section>

        <section className="block" aria-labelledby="soon-h">
          <div className="block-head">
            <h2 id="soon-h" className="block-title">Next 10 days</h2>
            <button className="link-btn" onClick={() => go('recurring')}>All recurring</button>
          </div>
          {data.upcoming.length ? (
            <ul className="soon-list">
              {data.upcoming.map((u, i) => (
                <li key={i}>
                  <span className="soon-date">{dayLabel(u.date, data.today)}</span>
                  <span className="soon-name">{u.name}</span>
                  <Money value={u.type === 'income' ? u.amount : -u.amount} currency={currency} whole tone="auto" sign />
                </li>
              ))}
            </ul>
          ) : <p className="quiet">No regular bills or income expected in the next 10 days.</p>}
        </section>
      </div>

      <section className="block" aria-labelledby="recent-h">
        <div className="block-head">
          <h2 id="recent-h" className="block-title">Latest entries</h2>
          <button className="link-btn" onClick={() => go('ledger')}>Open ledger</button>
        </div>
        <table className="ledger compact">
          <tbody>
            {data.recent.map((tx) => (
              <tr key={tx.id} onClick={() => openEntry(tx)} className="clickable">
                <td className="c-date">{shortDate(tx.date)}</td>
                <td className="c-desc">
                  <span className="desc-title">{tx.title}</span>
                  <span className="desc-meta">{tx.category}{tx.flag ? <em className="flag">{tx.flag}</em> : null}</span>
                </td>
                <td className="c-amt">
                  <Money value={tx.type === 'income' ? tx.display_amount : -tx.display_amount} currency={currency} tone="auto" sign />
                  {tx.currency !== currency && <span className="orig">{money(tx.amount, tx.currency)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
