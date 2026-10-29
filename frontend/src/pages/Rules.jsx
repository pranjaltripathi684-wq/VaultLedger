import React, { useState } from 'react'
import { send, useApi } from '../lib.js'
import { ErrorNote, Field, Loading, PageHead } from '../ui.jsx'

export default function Rules({ refreshKey, refresh, showToast }) {
  const { data, error, reload } = useApi('/api/rules', refreshKey)
  const { data: cats } = useApi('/api/categories', refreshKey)
  const [form, setForm] = useState({ keyword: '', category: '', apply_existing: true })
  const [formError, setFormError] = useState('')
  const [probe, setProbe] = useState('')
  const [probeResult, setProbeResult] = useState(null)

  if (!data && error) return <><PageHead title="Categories & rules" /><ErrorNote message={error} onRetry={reload} /></>
  if (!data) return <><PageHead title="Categories & rules" /><Loading /></>

  const save = async (e) => {
    e.preventDefault()
    setFormError('')
    try {
      await send('/api/rules', form)
      showToast(form.apply_existing ? `Rule saved and applied to existing entries containing “${form.keyword}”.` : 'Rule saved.')
      setForm({ keyword: '', category: '', apply_existing: true })
      refresh()
    } catch (err) { setFormError(err.message) }
  }
  const remove = async (r) => {
    await send(`/api/rules/${r.id}`, undefined, 'DELETE')
    refresh()
  }
  const test = async (e) => {
    e.preventDefault()
    if (!probe.trim()) return
    const r = await fetch(`/api/suggest?title=${encodeURIComponent(probe)}`).then((x) => x.json())
    setProbeResult(r)
  }

  const SOURCE = { rule: 'from a rule', history: 'learned from your entries', keyword: 'from common words' }

  return (
    <>
      <PageHead title="Categories & rules" note="VaultLedger picks a category from your past entries, then from common words. A rule always wins over both." />

      <div className="split even">
        <section className="block" aria-labelledby="rule-add">
          <h2 id="rule-add" className="block-title">Add a rule</h2>
          <form className="form" onSubmit={save}>
            {formError && <p className="form-error">{formError}</p>}
            <div className="form-row">
              <Field label="When the description contains" className="grow">
                <input value={form.keyword} onChange={(e) => setForm({ ...form, keyword: e.target.value })} placeholder="zomato" required />
              </Field>
              <Field label="Use category" className="grow">
                <input list="rule-cats" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} required />
                <datalist id="rule-cats">{(cats?.categories || []).map((c) => <option key={c} value={c} />)}</datalist>
              </Field>
            </div>
            <label className="check">
              <input type="checkbox" checked={form.apply_existing} onChange={(e) => setForm({ ...form, apply_existing: e.target.checked })} />
              Also recategorize existing entries that match
            </label>
            <div><button className="btn btn-primary" type="submit">Save rule</button></div>
          </form>
        </section>

        <section className="block" aria-labelledby="rule-test">
          <h2 id="rule-test" className="block-title">Try a description</h2>
          <form className="inline-form wide" onSubmit={test}>
            <input value={probe} onChange={(e) => setProbe(e.target.value)} placeholder="Swiggy order" aria-label="Description to test" />
            <button className="btn" type="submit">Check</button>
          </form>
          {probeResult && (
            probeResult.suggestions.length ? (
              <ol className="probe">
                {probeResult.suggestions.map((s) => (
                  <li key={s.category}><b>{s.category}</b> <span className="quiet">{Math.round(s.score * 100)}%, {SOURCE[s.source]}</span></li>
                ))}
              </ol>
            ) : <p className="quiet">No idea yet. Add a rule, or categorize a few entries like it and it will learn.</p>
          )}
        </section>
      </div>

      <section className="block" aria-labelledby="rules-h">
        <h2 id="rules-h" className="block-title">Your rules</h2>
        {data.rules.length ? (
          <table className="plain">
            <thead><tr><th>Contains</th><th>Category</th><th className="c-num">Matching entries</th><th /></tr></thead>
            <tbody>
              {data.rules.map((r) => (
                <tr key={r.id}>
                  <td>{r.keyword}</td>
                  <td>{r.category}</td>
                  <td className="c-num">{r.matches}</td>
                  <td className="c-act"><button className="link-btn" onClick={() => remove(r)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="quiet">No rules yet. Most of the time learning from your entries is enough; add a rule when a shop name keeps landing in the wrong place.</p>}
      </section>
    </>
  )
}
