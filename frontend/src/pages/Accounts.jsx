import React, { useState } from 'react'
import { CURRENCIES, money, send, useApi } from '../lib.js'
import { Dialog, Empty, ErrorNote, Field, Loading, Money, PageHead } from '../ui.jsx'

const TYPES = { checking: 'Current account', savings: 'Savings', credit: 'Credit card', credit_card: 'Credit card', cash: 'Cash', crypto: 'Crypto wallet', wallet: 'Wallet' }

export default function Accounts({ currency, refreshKey, refresh, showToast }) {
  const { data, error, reload } = useApi(`/api/hub?currency=${currency}`, refreshKey)
  const { data: reports } = useApi(`/api/reports?currency=${currency}`, refreshKey)
  const [dialog, setDialog] = useState(null)
  const [deposit, setDeposit] = useState({})

  if (!data && error) return <><PageHead title="Accounts & goals" /><ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <><PageHead title="Accounts & goals" /><Loading /></>

  // Typical amount kept per month, from complete months, for goal timing
  let monthlyKept = null
  if (reports && reports.months.length > 1) {
    const n = reports.months.length - 1
    const from = Math.max(0, n - 3)
    const kept = reports.income.slice(from, n).map((v, i) => v - reports.expenses[from + i])
    monthlyKept = kept.reduce((s, v) => s + v, 0) / (kept.length || 1)
  }
  const total = data.accounts.reduce((s, a) => s + a.balance_disp, 0)

  const doDeposit = async (goal) => {
    const amount = parseFloat(deposit[goal.id])
    if (!(amount > 0)) return
    try {
      await send(`/api/goals/${goal.id}/deposit`, { amount })
      setDeposit((d) => ({ ...d, [goal.id]: '' }))
      showToast(`Added ${money(amount, goal.currency)} to ${goal.title}.`)
      refresh()
    } catch (e) { showToast(e.message) }
  }
  const removeGoal = async (goal) => {
    if (!window.confirm(`Delete the goal “${goal.title}”?`)) return
    await send(`/api/goals/${goal.id}`, undefined, 'DELETE')
    refresh()
  }
  const removeAccount = async (acc) => {
    if (!window.confirm(`Remove ${acc.name}? Its entries stay in the ledger.`)) return
    await send(`/api/accounts/${acc.id}`, undefined, 'DELETE')
    refresh()
  }

  return (
    <>
      <PageHead title="Accounts & goals">
        <button className="btn" onClick={() => setDialog('account')}>Add account</button>
        <button className="btn" onClick={() => setDialog('goal')}>Add goal</button>
      </PageHead>

      <section className="block" aria-labelledby="acc-h">
        <div className="block-head">
          <h2 id="acc-h" className="block-title">Accounts</h2>
          {data.accounts.length > 1 && <span className="quiet">Together <Money value={total} currency={currency} whole /></span>}
        </div>
        {data.accounts.length ? (
          <table className="plain">
            <thead><tr><th>Account</th><th>Type</th><th className="c-num">Balance</th><th /></tr></thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.id}>
                  <td><span className="swatch" style={{ background: a.color }} />{a.name}</td>
                  <td>{TYPES[a.type] || a.type}{a.currency !== currency ? `, ${a.currency}` : ''}</td>
                  <td className="c-num"><Money value={a.balance_disp} currency={currency} tone="auto" /></td>
                  <td className="c-act"><button className="link-btn" onClick={() => removeAccount(a)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>Add your bank accounts, cards and cash to see a balance for each. Entries are booked to an account from the entry form, or by writing “via HDFC”.</Empty>}
      </section>

      <section className="block" aria-labelledby="goal-h">
        <h2 id="goal-h" className="block-title">Savings goals</h2>
        {data.goals.length ? (
          <ul className="goal-list">
            {data.goals.map((g) => {
              const remaining = Math.max(0, g.target_disp - g.current_disp)
              const months = monthlyKept > 0 && remaining > 0 ? Math.ceil(remaining / monthlyKept) : null
              return (
                <li key={g.id} className="goal">
                  <div className="goal-top">
                    <h3>{g.title}</h3>
                    <span className="budget-nums"><Money value={g.current_disp} currency={currency} whole /> <span className="of">of</span> <Money value={g.target_disp} currency={currency} whole /></span>
                  </div>
                  <div className="pace pace-goal" aria-hidden="true"><span className="pace-fill" style={{ width: `${g.percent}%` }} /></div>
                  <div className="goal-foot">
                    <p className="quiet">
                      {remaining <= 0 ? 'Reached.' : <>{money(remaining, currency, { whole: true })} to go{months ? `, about ${months} ${months === 1 ? 'month' : 'months'} at what you usually keep each month` : ''}.</>}
                    </p>
                    <form className="inline-form" onSubmit={(e) => { e.preventDefault(); doDeposit(g) }}>
                      <input type="number" min="0.01" step="0.01" placeholder={`Add (${g.currency})`} aria-label={`Amount to add to ${g.title} in ${g.currency}`}
                        value={deposit[g.id] || ''} onChange={(e) => setDeposit((d) => ({ ...d, [g.id]: e.target.value }))} />
                      <button className="btn" type="submit">Add</button>
                      <button type="button" className="link-btn" onClick={() => removeGoal(g)}>Delete</button>
                    </form>
                  </div>
                </li>
              )
            })}
          </ul>
        ) : <Empty>No goals yet. A goal shows how long it will take at the rate you usually save.</Empty>}
      </section>

      <section className="block" aria-labelledby="tax-h">
        <h2 id="tax-h" className="block-title">Tax set-aside</h2>
        <p className="quiet">
          A rough reserve of 25% on net income so far: <Money value={data.tax.est_tax_amount} currency={currency} whole />, or <Money value={data.tax.est_quarterly_payment} currency={currency} whole /> a quarter. This is a planning figure, not tax advice.
        </p>
      </section>

      {dialog === 'account' && <AccountDialog currency={currency} onClose={() => setDialog(null)} onSaved={(n) => { setDialog(null); showToast(`Saved ${n}.`); refresh() }} />}
      {dialog === 'goal' && <GoalDialog currency={currency} onClose={() => setDialog(null)} onSaved={(n) => { setDialog(null); showToast(`Added the goal ${n}.`); refresh() }} />}
    </>
  )
}

function AccountDialog({ currency, onClose, onSaved }) {
  const [form, setForm] = useState({ name: '', account_type: 'savings', initial_balance: '', currency, color: '#2C3E95' })
  const [error, setError] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    try { await send('/api/accounts', form); onSaved(form.name) } catch (err) { setError(err.message) }
  }
  return (
    <Dialog title="Add account" onClose={onClose}
      footer={<><span className="spacer" /><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" type="submit" form="acc-form">Add account</button></>}>
      <form id="acc-form" className="form" onSubmit={submit}>
        {error && <p className="form-error">{error}</p>}
        <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="HDFC Savings" required /></Field>
        <div className="form-row">
          <Field label="Type" className="grow">
            <select value={form.account_type} onChange={(e) => setForm({ ...form, account_type: e.target.value })}>
              {['savings', 'checking', 'credit', 'cash', 'wallet', 'crypto'].map((t) => <option key={t} value={t}>{TYPES[t]}</option>)}
            </select>
          </Field>
          <Field label="Colour"><input type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} /></Field>
        </div>
        <div className="form-row">
          <Field label="Opening balance" className="grow"><input type="number" step="0.01" value={form.initial_balance} onChange={(e) => setForm({ ...form, initial_balance: e.target.value })} placeholder="0" /></Field>
          <Field label="Currency"><select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{CURRENCIES.map(([c]) => <option key={c}>{c}</option>)}</select></Field>
        </div>
      </form>
    </Dialog>
  )
}

function GoalDialog({ currency, onClose, onSaved }) {
  const [form, setForm] = useState({ title: '', target_amount: '', current_amount: '', currency, target_date: '' })
  const [error, setError] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    try { await send('/api/goals', form); onSaved(form.title) } catch (err) { setError(err.message) }
  }
  return (
    <Dialog title="Add goal" onClose={onClose}
      footer={<><span className="spacer" /><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" type="submit" form="goal-form">Add goal</button></>}>
      <form id="goal-form" className="form" onSubmit={submit}>
        {error && <p className="form-error">{error}</p>}
        <Field label="What for"><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Emergency fund" required /></Field>
        <div className="form-row">
          <Field label="Target" className="grow"><input type="number" min="1" step="1" value={form.target_amount} onChange={(e) => setForm({ ...form, target_amount: e.target.value })} required /></Field>
          <Field label="Saved so far" className="grow"><input type="number" min="0" step="1" value={form.current_amount} onChange={(e) => setForm({ ...form, current_amount: e.target.value })} placeholder="0" /></Field>
          <Field label="Currency"><select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{CURRENCIES.map(([c]) => <option key={c}>{c}</option>)}</select></Field>
        </div>
      </form>
    </Dialog>
  )
}
