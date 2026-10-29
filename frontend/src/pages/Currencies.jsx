import React, { useEffect, useState } from 'react'
import { send } from '../lib.js'
import { Empty, ErrorNote, Loading, Money, PageHead } from '../ui.jsx'

export default function Currencies({ currency, refreshKey }) {
  const [inputs, setInputs] = useState({})
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [reloadKey, setReloadKey] = useState(0)

  const simulated = {}
  Object.entries(inputs).forEach(([c, v]) => { const n = parseFloat(v); if (n > 0) simulated[c] = n })
  const key = JSON.stringify(simulated)

  useEffect(() => {
    let live = true
    const t = setTimeout(async () => {
      setState((s) => ({ ...s, loading: true }))
      try {
        const data = await send(`/api/fx?currency=${currency}`, { rates: JSON.parse(key) })
        if (live) setState({ data, error: null, loading: false })
      } catch (e) {
        if (live) setState((s) => ({ ...s, error: e.message, loading: false }))
      }
    }, Object.keys(inputs).length ? 300 : 0)
    return () => { live = false; clearTimeout(t) }
  }, [currency, refreshKey, key, reloadKey])

  const { data, error } = state
  if (!data && error) return <><PageHead title="Currencies" /><ErrorNote message={error} onRetry={() => setReloadKey((k) => k + 1)} /></>
  if (!data) return <><PageHead title="Currencies" /><Loading /></>

  const a = data.analysis
  const held = a.currencies
  const changed = Object.keys(simulated).some((c) => simulated[c] !== data.default_rates[c])

  return (
    <>
      <PageHead title="Currencies" note={`Money you hold in currencies other than ${currency}: what it cost you and what it is worth today. Change a rate to see what a move would do.`} />

      <section className="figures" aria-label="Foreign currency totals">
        <div className="figure">
          <h2>Held in other currencies</h2>
          <Money value={a.total_value} currency={currency} whole className="figure-value" />
          <p>Worth in {currency} at {changed ? 'your test rates' : 'standard rates'}</p>
        </div>
        <div className="figure">
          <h2>Gain or loss on paper</h2>
          <Money value={a.total_unrealized_gain} currency={currency} whole sign tone="auto" className="figure-value" />
          <p>Today's value against what the money cost when it came in</p>
        </div>
        <div className="figure">
          <h2>Gain or loss realised</h2>
          <Money value={a.total_realized_gain} currency={currency} whole sign tone="auto" className="figure-value" />
          <p>Locked in when foreign money was spent</p>
        </div>
      </section>

      <section className="block" aria-labelledby="rates-h">
        <div className="block-head">
          <h2 id="rates-h" className="block-title">Balances and rates {state.loading && <span className="quiet">updating</span>}</h2>
          {changed && <button className="link-btn" onClick={() => setInputs({})}>Back to standard rates</button>}
        </div>
        <table className="plain">
          <thead>
            <tr><th>Currency</th><th className="c-num">Balance</th><th className="c-num">1 unit in {currency}</th><th className="c-num">Cost</th><th className="c-num">Worth now</th><th className="c-num">On paper</th><th className="c-num">Realised</th></tr>
          </thead>
          <tbody>
            {Object.keys(data.rates).map((c) => {
              const h = held.find((x) => x.currency === c) || { balance: 0, cost: 0, value: 0, unrealized: 0, realized: 0 }
              return (
                <tr key={c}>
                  <td>{c}</td>
                  <td className="c-num">{h.balance.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                  <td className="c-num">
                    <input className="rate-input" type="number" step="any" min="0" aria-label={`${currency} value of 1 ${c}`}
                      value={inputs[c] ?? String(data.rates[c])} onChange={(e) => setInputs((s) => ({ ...s, [c]: e.target.value }))} />
                  </td>
                  <td className="c-num"><Money value={h.cost} currency={currency} /></td>
                  <td className="c-num"><Money value={h.value} currency={currency} /></td>
                  <td className="c-num"><Money value={h.unrealized} currency={currency} sign tone="auto" /></td>
                  <td className="c-num"><Money value={h.realized} currency={currency} sign tone="auto" /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {!held.length && <Empty>No entries in other currencies yet. Anything you record in a currency other than {currency} is tracked here automatically.</Empty>}
      </section>
    </>
  )
}
