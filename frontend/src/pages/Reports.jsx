import React from 'react'
import { money, useApi } from '../lib.js'
import { Empty, ErrorNote, Loading, Money, MonthBars, PageHead, Spark } from '../ui.jsx'

export default function Reports({ currency, refreshKey }) {
  const { data, error, reload } = useApi(`/api/reports?currency=${currency}`, refreshKey)
  if (!data && error) return <><PageHead title="Reports" /><ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <><PageHead title="Reports" /><Loading /></>
  if (!data.months.length) return <><PageHead title="Reports" /><Empty>Reports fill in once you have entries.</Empty></>

  const totalOut = data.categories.reduce((s, c) => s + c.total, 0) || 1
  const p = data.projection
  const rows = data.months.map((m, i) => ({ m, label: data.labels[i], inc: data.income[i], out: data.expenses[i], rate: data.savings_rate[i] }))
  const rated = rows.filter((r) => r.rate !== null)
  const avgRate = rated.length ? rated.reduce((s, r) => s + r.rate, 0) / rated.length : null

  return (
    <>
      <PageHead title="Reports" note={`The last ${data.months.length} ${data.months.length === 1 ? 'month' : 'months'}, in ${currency}.`} />

      <div className="split">
        <section className="block" aria-labelledby="flow-h">
          <h2 id="flow-h" className="block-title">Money in and out</h2>
          <MonthBars labels={data.labels} income={data.income} expenses={data.expenses} currency={currency} />
        </section>
        <section className="block" aria-labelledby="outlook-h">
          <h2 id="outlook-h" className="block-title">Twelve months from now</h2>
          {p ? (
            <div className="outlook">
              <p className="outlook-lead">
                If the coming year looks like the past {data.months.length} {data.months.length === 1 ? 'month' : 'months'}, your balance most likely ends near <Money value={p.projected_median} currency={currency} whole />.
              </p>
              <dl className="outlook-range">
                <div><dt>Cautious case</dt><dd><Money value={p.projected_pessimistic} currency={currency} whole tone={p.projected_pessimistic < 0 ? 'out' : ''} /></dd></div>
                <div><dt>Likely</dt><dd><Money value={p.projected_median} currency={currency} whole /></dd></div>
                <div><dt>Good case</dt><dd><Money value={p.projected_optimistic} currency={currency} whole /></dd></div>
              </dl>
              <p className="quiet">
                From 1,000 simulated years using your monthly ups and downs. The cautious and good cases are the 5th and 95th percentiles.
                {p.risk_of_ruin > 0 ? ` In ${p.risk_of_ruin}% of them the balance dipped below zero at some point.` : ' None of them dipped below zero.'}
              </p>
            </div>
          ) : <p className="quiet">Not enough history yet.</p>}
        </section>
      </div>

      <section className="block" aria-labelledby="months-h">
        <h2 id="months-h" className="block-title">Month by month</h2>
        <table className="plain">
          <thead><tr><th>Month</th><th className="c-num">In</th><th className="c-num">Out</th><th className="c-num">Kept</th><th className="c-num">Saved</th></tr></thead>
          <tbody>
            {rows.slice().reverse().map((r) => (
              <tr key={r.m}>
                <td>{r.label}</td>
                <td className="c-num"><Money value={r.inc} currency={currency} whole /></td>
                <td className="c-num"><Money value={r.out} currency={currency} whole /></td>
                <td className="c-num"><Money value={r.inc - r.out} currency={currency} whole tone="auto" /></td>
                <td className="c-num">{r.rate === null ? '' : `${r.rate}%`}</td>
              </tr>
            ))}
          </tbody>
          {avgRate !== null && (
            <tfoot><tr><td colSpan="4">Average share of income kept</td><td className="c-num">{avgRate.toFixed(1)}%</td></tr></tfoot>
          )}
        </table>
      </section>

      <section className="block" aria-labelledby="cats-h">
        <h2 id="cats-h" className="block-title">Where the money went</h2>
        <table className="plain">
          <thead><tr><th>Category</th><th>Trend</th><th className="c-num">Share</th><th className="c-num">Total</th><th className="c-num">This month</th></tr></thead>
          <tbody>
            {data.categories.map((c) => (
              <tr key={c.category}>
                <td>{c.category}</td>
                <td><Spark values={c.by_month} /></td>
                <td className="c-num">{((c.total / totalOut) * 100).toFixed(0)}%</td>
                <td className="c-num"><Money value={c.total} currency={currency} whole /></td>
                <td className="c-num"><Money value={c.by_month[c.by_month.length - 1]} currency={currency} whole /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
