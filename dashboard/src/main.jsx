import { StrictMode, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

async function api(path, options = {}, csrf = '') {
  const method = options.method || 'GET'
  const headers = { ...(options.headers || {}) }
  const body = options.body && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body
  if (body) headers['Content-Type'] = 'application/json'
  if (!['GET', 'HEAD'].includes(method) && csrf) headers['X-CSRF-Token'] = csrf
  const response = await fetch(path, { credentials: 'same-origin', ...options, method, headers, body })
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || data.error || `Request failed (${response.status})`)
  return data
}

const money = micros => micros ? `$${(micros / 1_000_000).toFixed(2)}` : '$0.00'
const tokens = value => Number(value || 0).toLocaleString()
const played = seconds => {
  const total = Number(seconds || 0), hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60)
  return `${hours}h ${minutes}m`
}

function Login({ onLogin }) {
  const [password, setPassword] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    try { onLogin((await api('/admin/v1/session', { method: 'POST', body: { password } })).csrf_token) }
    catch (reason) { setError(reason.message) } finally { setBusy(false) }
  }
  return <main className="login-shell"><section className="login-card"><div className="sigil">SF</div><p className="eyebrow">A world waiting for you</p><h1>Enter Soulforge</h1><p className="muted">Wake your private Azeroth, live in it, then leave it exactly where you stopped.</p><form onSubmit={submit}><label>Admin password<input autoFocus type="password" value={password} onChange={e => setPassword(e.target.value)} /></label>{error && <p className="error">{error}</p>}<button className="primary wide" disabled={busy || !password}>{busy ? 'Opening…' : 'Enter the forge'}</button></form></section></main>
}

function ForgeWorld({ csrf, refresh, notify }) {
  const [seed, setSeed] = useState(''), [faction, setFaction] = useState('alliance'), [role, setRole] = useState('dps')
  const [job, setJob] = useState(null), [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!job || ['complete', 'failed'].includes(job.status)) return
    const timer = setInterval(async () => {
      try {
        const next = await api(`/admin/v1/jobs/${job.id || job.job_id}`); setJob(next)
        if (next.status === 'complete') { clearInterval(timer); refresh() }
      } catch (error) { notify(error.message, true) }
    }, 2000)
    return () => clearInterval(timer)
  }, [job?.status])
  async function forge() {
    setBusy(true)
    try { setJob(await api('/admin/v1/world/forge', { method: 'POST', body: { seed_prompt: seed, faction, player_role: role } }, csrf)) }
    catch (error) { notify(error.message, true) } finally { setBusy(false) }
  }
  return <section className="forge-card"><p className="eyebrow">First awakening</p><h2>What kind of world do you want to live in?</h2><p className="lede">This prompt becomes immutable canon. It shapes the people, their voices, their loyalties, the rumors they spread, and what the world remembers.</p><label>W0rld prompt<textarea className="seed-input" value={seed} onChange={e => setSeed(e.target.value)} placeholder="A hopeful but weathered fresh realm where every inn has old stories, rival guilds remember grudges, and companionship is earned…" /></label><div className="choice-row"><label>Faction<select value={faction} onChange={e => setFaction(e.target.value)}><option value="alliance">Alliance</option><option value="horde">Horde</option></select></label><label>Your dungeon role<select value={role} onChange={e => setRole(e.target.value)}><option value="tank">Tank</option><option value="healer">Healer</option><option value="dps">Damage</option></select></label></div><p className="hint">Soulforge will select four complementary Playerbots and forge their identities around the generated world.</p><button className="primary forge-button" disabled={busy || seed.trim().length < 20 || (job && !['failed', 'complete'].includes(job.status))} onClick={forge}>{busy ? 'Lighting the forge…' : 'Forge fresh world'}</button>{job && <div className={`job ${job.status}`}><span className="spinner" /><div><strong>{job.progress || 'Waiting for the forge'}</strong><small>{job.status === 'failed' ? job.error : 'You can leave this page open while canon is formed.'}</small></div></div>}</section>
}

function ServiceGrid({ services = [] }) {
  return <div className="service-grid">{services.map(service => { const healthy = service.running && (!service.health || service.health === 'healthy'); return <div className="service" key={service.service}><span className={`dot ${healthy ? 'online' : 'offline'}`} /><div><strong>{service.service.replace('ac-', '')}</strong><small>{service.health || service.status}</small></div></div> })}</div>
}

function Home({ csrf, notify }) {
  const [data, setData] = useState(null), [busy, setBusy] = useState('')
  const load = () => api('/admin/v1/home').then(setData).catch(error => notify(error.message, true))
  useEffect(() => { load(); const timer = setInterval(load, 10000); return () => clearInterval(timer) }, [])
  async function worldAction(action) { setBusy(action); try { await api(`/admin/v1/world/actions/${action}`, { method: 'POST' }, csrf); await load() } catch (error) { notify(error.message, true) } finally { setBusy('') } }
  async function toggleAI() { try { await api('/admin/v1/ai/state', { method: 'PUT', body: { enabled: !data.ai.enabled } }, csrf); await load() } catch (error) { notify(error.message, true) } }
  if (!data) return <div className="loading">Reading your world…</div>
  if (!data.world) return <div className="page"><ForgeWorld csrf={csrf} refresh={load} notify={notify} /></div>
  const worldOnline = data.services?.find(service => service.service === 'ac-worldserver')?.running
  return <div className="page"><header className="page-head"><div><p className="eyebrow">{data.world.phase.replace('_', ' ')}</p><h2>{data.world.canon.premise || 'Your fresh Azeroth'}</h2></div><span className={`realm-state ${worldOnline ? 'up' : 'down'}`}>{worldOnline ? `${data.humans_online || 0} playing` : 'World paused'}</span></header><section className="world-hero"><div><span className="kicker">{worldOnline ? 'The world is awake' : 'Nothing moves while you are away'}</span><h3>{worldOnline ? 'Your story is waiting in Azeroth.' : 'Return exactly where you left it.'}</h3><p>{worldOnline ? 'Launch Wow.exe and enter the realm. World time advances only while a human is playing.' : 'Starting wakes the realm; you still launch Wow.exe yourself.'}</p></div><div className="actions">{worldOnline ? <button className="danger" disabled={!!busy} onClick={() => worldAction('leave')}>Leave world</button> : <button className="primary" disabled={!!busy} onClick={() => worldAction('enter')}>Enter world</button>}</div></section><section className="metric-grid"><article><small>World lived</small><strong>{played(data.world.played_seconds)}</strong><span>human playtime only</span></article><article><small>Companions</small><strong>{data.companions.length}</strong><span>{data.companions.map(item => item.name).join(', ') || 'awaiting the forge'}</span></article><article><small>AI this month</small><strong>{tokens(data.usage.total_tokens)}</strong><span>{money(data.usage.estimated_cost_micros)} estimated</span></article><article><small>Current phase</small><strong>Fresh</strong><span>staged Vanilla</span></article></section><div className="dashboard-grid"><section className="panel"><div className="section-title"><h3>AI pulse</h3><button className={`kill-switch ${data.ai.enabled ? 'enabled' : 'stopped'}`} onClick={toggleAI}>{data.ai.enabled ? 'AI enabled' : 'AI stopped'}</button></div><p className="muted">Director: {data.routes.director?.model}<br />Dialogue: {data.routes.dialogue?.model}</p><div className="usage-bar"><span style={{ width: data.usage.monthly_cap_micros ? `${Math.min(data.usage.estimated_cost_micros / data.usage.monthly_cap_micros * 100, 100)}%` : '0%' }} /></div><small>{data.usage.monthly_cap_micros ? `${money(data.usage.estimated_cost_micros)} of ${money(data.usage.monthly_cap_micros)} cap` : 'No monthly hard cap'}</small></section><section className="panel"><div className="section-title"><h3>Whispers on the wind</h3><span>no spoilers</span></div>{data.rumors.length ? data.rumors.map(rumor => <article className="rumor" key={rumor.id}><strong>{rumor.title}</strong><p>{rumor.hint}</p></article>) : <p className="muted">The world is still finding its voice.</p>}</section></div><section className="panel"><div className="section-title"><h3>Server details</h3><span>refreshes every 10 seconds</span></div><ServiceGrid services={data.services} />{data.control_error && <p className="error">{data.control_error}</p>}</section></div>
}

function WorldPage({ notify }) {
  const [world, setWorld] = useState(null), [memories, setMemories] = useState([]), [rumors, setRumors] = useState([])
  useEffect(() => { Promise.all([api('/admin/v1/world'), api('/admin/v1/world/chronicle'), api('/admin/v1/world/rumors')]).then(([w, m, r]) => { setWorld(w.world); setMemories(m.memories); setRumors(r.rumors) }).catch(e => notify(e.message, true)) }, [])
  if (!world) return <div className="page empty"><h2>No world has been forged yet.</h2></div>
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Immutable canon</p><h2>The world you asked for</h2></div><span className="count">{played(world.played_seconds)} lived</span></header><section className="panel canon"><blockquote>{world.seed_prompt}</blockquote><div className="canon-grid">{Object.entries(world.canon).filter(([, value]) => !Array.isArray(value) || value.length).map(([key, value]) => <article key={key}><small>{key.replaceAll('_', ' ')}</small>{Array.isArray(value) ? <ul>{value.map((item, index) => <li key={index}>{typeof item === 'string' ? item : item.hint || item.title}</li>)}</ul> : <p>{typeof value === 'object' ? JSON.stringify(value) : value}</p>}</article>)}</div></section><div className="dashboard-grid"><section className="panel"><div className="section-title"><h3>Chronicle</h3><span>{memories.length} distilled memories</span></div><p className="hint">Casual chat ages out. Only durable facts, relationships, decisions, and events enter this ledger.</p>{memories.map(memory => <article className="memory" key={memory.id}><small>{memory.kind} · {new Date(memory.created_at).toLocaleString()}</small><p>{memory.redacted ? 'This memory was redacted.' : memory.text}</p></article>)}{!memories.length && <p className="muted">Your history begins when you enter the world.</p>}</section><section className="panel"><div className="section-title"><h3>Rumors & tensions</h3><span>future hints</span></div>{rumors.map(rumor => <article className="rumor" key={rumor.id}><strong>{rumor.title}</strong><p>{rumor.hint}</p></article>)}</section></div></div>
}

function Companions({ csrf, notify }) {
  const [companions, setCompanions] = useState([]), [bots, setBots] = useState([]), [showAdd, setShowAdd] = useState(false)
  const load = () => Promise.all([api('/admin/v1/world/companions'), api('/admin/v1/bots')]).then(([c, b]) => { setCompanions(c.companions); setBots(b.bots) }).catch(e => notify(e.message, true))
  useEffect(() => { load() }, [])
  const bound = useMemo(() => new Set(companions.map(item => String(item.bot_guid))), [companions])
  async function promote(bot) { try { await api('/admin/v1/world/companions', { method: 'POST', body: { bot_guid: String(bot.guid), name: bot.name, role: 'dps' } }, csrf); setShowAdd(false); load() } catch (error) { notify(error.message, true) } }
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Your dungeon group</p><h2>Companions</h2></div><button onClick={() => setShowAdd(!showAdd)}>Add companion</button></header><div className="companion-grid">{companions.map(companion => <article className="companion" key={companion.bot_guid}><div className="portrait">{companion.name.slice(0, 1)}</div><div><span className="role">{companion.role}</span><h3>{companion.name}</h3><p>{companion.archetype}</p><small>{companion.memory_count} recent memory messages</small></div></article>)}</div>{showAdd && <section className="panel"><div className="section-title"><h3>Promote someone you met</h3><span>adds deep personal memory</span></div><div className="bot-list">{bots.filter(bot => !bound.has(String(bot.guid))).slice(0, 100).map(bot => <button key={bot.guid} onClick={() => promote(bot)}><strong>{bot.name}</strong><span>Level {bot.level} · class {bot.class}</span></button>)}</div></section>}</div>
}

function AIStudio({ csrf, notify }) {
  const empty = { name: '', kind: 'openai', base_url: 'https://api.openai.com', api_key: '', input_cost_micros: 0, cached_input_cost_micros: 0, output_cost_micros: 0 }
  const [providers, setProviders] = useState([]), [routes, setRoutes] = useState({}), [state, setState] = useState(null), [usage, setUsage] = useState(null), [form, setForm] = useState(empty)
  const load = () => Promise.all([api('/admin/v1/ai/providers'), api('/admin/v1/ai/routing'), api('/admin/v1/ai/state'), api('/admin/v1/ai/usage')]).then(([p, r, s, u]) => { setProviders(p.providers); setRoutes(r.routes); setState(s); setUsage(u) }).catch(e => notify(e.message, true))
  useEffect(() => { load() }, [])
  const set = (key, value) => setForm({ ...form, [key]: value })
  async function saveProvider() { try { await api('/admin/v1/ai/providers', { method: 'POST', body: { ...form, input_cost_micros: Number(form.input_cost_micros), cached_input_cost_micros: Number(form.cached_input_cost_micros), output_cost_micros: Number(form.output_cost_micros) } }, csrf); setForm(empty); load() } catch (error) { notify(error.message, true) } }
  async function saveRoutes() { try { await api('/admin/v1/ai/routing', { method: 'PUT', body: routes }, csrf); notify('AI routing saved'); load() } catch (error) { notify(error.message, true) } }
  async function saveState() { try { await api('/admin/v1/ai/state', { method: 'PUT', body: state }, csrf); notify('AI safeguards saved'); load() } catch (error) { notify(error.message, true) } }
  if (!state || !usage) return <div className="loading">Reading AI profiles…</div>
  const routeEditor = purpose => <section className="panel form-panel"><div className="section-title"><h3>{purpose === 'director' ? 'World director' : 'In-game dialogue'}</h3><span>{purpose}</span></div><label>Provider<select value={routes[purpose]?.provider_id || ''} onChange={e => setRoutes({ ...routes, [purpose]: { ...routes[purpose], provider_id: e.target.value } })}>{providers.filter(p => p.enabled).map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></label><label>Model<input value={routes[purpose]?.model || ''} onChange={e => setRoutes({ ...routes, [purpose]: { ...routes[purpose], model: e.target.value } })} /></label><div className="choice-row"><label>Temperature<input type="number" min="0" max="2" step="0.05" value={routes[purpose]?.temperature || 0} onChange={e => setRoutes({ ...routes, [purpose]: { ...routes[purpose], temperature: Number(e.target.value) } })} /></label><label>Max tokens<input type="number" min="32" max="4096" value={routes[purpose]?.max_tokens || 180} onChange={e => setRoutes({ ...routes, [purpose]: { ...routes[purpose], max_tokens: Number(e.target.value) } })} /></label></div></section>
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Local or paid</p><h2>AI Studio</h2></div><button className={`kill-switch ${state.enabled ? 'enabled' : 'stopped'}`} onClick={() => setState({ ...state, enabled: !state.enabled })}>{state.enabled ? 'AI enabled' : 'AI stopped'}</button></header><section className="metric-grid"><article><small>Monthly tokens</small><strong>{tokens(usage.total_tokens)}</strong><span>{usage.requests} requests</span></article><article><small>Estimated spend</small><strong>{money(usage.estimated_cost_micros)}</strong><span>provider bill is authoritative</span></article></section><div className="settings-grid">{routeEditor('director')}{routeEditor('dialogue')}</div><button className="primary save-settings" onClick={saveRoutes}>Save model routing</button><div className="dashboard-grid"><section className="panel form-panel"><div className="section-title"><h3>Safeguards</h3><span>persistent</span></div><label className="toggle"><input type="checkbox" checked={state.enabled} onChange={e => setState({ ...state, enabled: e.target.checked })} /><span />Allow all AI inference</label><label>Optional monthly cap in dollars<input type="number" min="0" step="1" value={state.monthly_cap_micros / 1_000_000} onChange={e => setState({ ...state, monthly_cap_micros: Math.round(Number(e.target.value) * 1_000_000) })} /></label><label>Auto-pause after last player leaves<input type="number" min="0" max="120" value={state.auto_stop_minutes} onChange={e => setState({ ...state, auto_stop_minutes: Number(e.target.value) })} /></label><button onClick={saveState}>Save safeguards</button></section><section className="panel"><div className="section-title"><h3>Configured providers</h3><span>{providers.length}</span></div>{providers.map(provider => <article className="provider" key={provider.id}><div><strong>{provider.name}</strong><small>{provider.kind} · {provider.has_secret ? 'key stored' : 'no key required'}</small></div><span className={`dot ${provider.enabled ? 'online' : 'offline'}`} /></article>)}</section></div><section className="panel form-panel"><div className="section-title"><h3>Add AI provider</h3><span>keys stay server-side</span></div><div className="settings-grid"><label>Name<input value={form.name} onChange={e => set('name', e.target.value)} placeholder="My OpenAI account" /></label><label>Type<select value={form.kind} onChange={e => set('kind', e.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="gemini">Gemini</option><option value="ollama">Ollama</option><option value="openai_compatible">OpenAI-compatible</option></select></label><label>Base URL<input value={form.base_url} onChange={e => set('base_url', e.target.value)} /></label><label>API key<input type="password" value={form.api_key} onChange={e => set('api_key', e.target.value)} /></label></div><details><summary>Optional cost rates</summary><p className="hint">Enter micro-dollars per million tokens. Leave zero when cost is unknown.</p><div className="choice-row"><label>Input<input type="number" value={form.input_cost_micros} onChange={e => set('input_cost_micros', e.target.value)} /></label><label>Cached input<input type="number" value={form.cached_input_cost_micros} onChange={e => set('cached_input_cost_micros', e.target.value)} /></label><label>Output<input type="number" value={form.output_cost_micros} onChange={e => set('output_cost_micros', e.target.value)} /></label></div></details><button className="primary" disabled={!form.name || !form.base_url} onClick={saveProvider}>Save provider</button><p className="hint">Paid providers receive relevant world canon, memories, and dialogue context. Add one only if you accept that data leaving your home server.</p></section></div>
}

function Advanced({ csrf, notify }) {
  const [settings, setSettings] = useState(null), [bots, setBots] = useState([])
  useEffect(() => { Promise.all([api('/admin/v1/server/settings'), api('/admin/v1/bots')]).then(([s, b]) => { setSettings(s); setBots(b.bots) }).catch(e => notify(e.message, true)) }, [])
  if (!settings) return <div className="loading">Reading advanced settings…</div>
  const set = (key, value) => setSettings({ ...settings, [key]: value })
  async function save() { try { await api('/admin/v1/server/settings', { method: 'PUT', body: { ...settings, random_bots: Number(settings.random_bots), max_added_bots: Number(settings.max_added_bots), new_character_level: Number(settings.new_character_level), player_limit: Number(settings.player_limit) } }, csrf); notify('Advanced settings applied') } catch (error) { notify(error.message, true) } }
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Use when needed</p><h2>Advanced</h2></div></header><section className="notice"><strong>Everyday controls live on Home.</strong><p>These settings change realm behavior and may restart the worldserver.</p></section><div className="settings-grid"><section className="panel form-panel"><h3>Realm</h3><label>Realm name<input value={settings.realm_name} onChange={e => set('realm_name', e.target.value)} /></label><label>Random world population<input type="number" min="0" max="2000" value={settings.random_bots} onChange={e => set('random_bots', e.target.value)} /></label><label>Maximum added companions<input type="number" min="1" max="80" value={settings.max_added_bots} onChange={e => set('max_added_bots', e.target.value)} /></label><label>New-character level<input type="number" min="1" max="80" value={settings.new_character_level} onChange={e => set('new_character_level', e.target.value)} /></label><button className="primary" onClick={save}>Apply settings</button></section><section className="panel"><div className="section-title"><h3>Bot population</h3><span>{bots.length}</span></div><p className="muted">{bots.filter(bot => bot.online).length} online · {bots.filter(bot => bot.player_added).length} player-added</p><p className="hint">World population bots share canon and world memory. Promoted companions receive deep personal continuity.</p></section></div></div>
}

function AddonPage() {
  return <div className="page"><header className="page-head"><div><p className="eyebrow">No more command typing</p><h2>Soulforge Commander</h2></div><a className="button primary" href="/admin/v1/addon/download">Download addon</a></header><section className="world-hero"><div><span className="kicker">WoW 3.3.5a · Interface 30300</span><h3>A Mass Effect-style command wheel.</h3><p>Hold one mapped button, move the mouse toward Assemble, Follow, Stay, Flee, Attack, Tank Pull, Rebuff, or Reset, then release to activate it.</p></div></section><section className="panel"><h3>Install once</h3><ol><li>Download and extract <code>SoulforgeCommander.zip</code>.</li><li>Place <code>SoulforgeCommander</code> in <code>Interface/AddOns</code> inside your legal 3.3.5a client.</li><li>Restart Wow.exe and enable the addon on the character screen.</li><li>Open WoW’s Key Bindings, find <strong>Soulforge Commander</strong>, and map <strong>Hold command wheel</strong>.</li><li>Choose <strong>Assemble</strong> once after login to bring Richpiana, Wife, Donaldtrump, and Samhyde into your party.</li><li>Hold the button, move toward a command, and release. The mouse wheel changes the target scope; direct mouse clicks also work.</li></ol><p className="hint">The addon sends only user-initiated Playerbots commands. It never contacts the AI service and never changes a binding without you.</p></section></div>
}

function App() {
  const [csrf, setCsrf] = useState(null), [checking, setChecking] = useState(true), [tab, setTab] = useState('home'), [toast, setToast] = useState(null)
  const notify = (message, error = false) => { setToast({ message, error }); setTimeout(() => setToast(null), 4500) }
  useEffect(() => { api('/admin/v1/session').then(x => setCsrf(x.csrf_token)).catch(() => {}).finally(() => setChecking(false)) }, [])
  async function logout() { try { await api('/admin/v1/session', { method: 'DELETE' }, csrf) } finally { setCsrf(null) } }
  if (checking) return <div className="loading full">Lighting the forge…</div>
  if (!csrf) return <Login onLogin={setCsrf} />
  const pages = { home: <Home csrf={csrf} notify={notify} />, world: <WorldPage notify={notify} />, companions: <Companions csrf={csrf} notify={notify} />, ai: <AIStudio csrf={csrf} notify={notify} />, addon: <AddonPage />, advanced: <Advanced csrf={csrf} notify={notify} /> }
  const nav = [['home', 'Home'], ['world', 'World'], ['companions', 'Companions'], ['ai', 'AI Studio'], ['addon', 'Bot addon'], ['advanced', 'Advanced']]
  return <div className="app-shell"><aside><div className="brand"><div className="sigil small">SF</div><div><strong>Soulforge</strong><small>Your living Azeroth</small></div></div><nav>{nav.map(([key, label]) => <button className={tab === key ? 'active' : ''} key={key} onClick={() => setTab(key)}>{label}</button>)}</nav><button className="logout" onClick={logout}>Lock dashboard</button></aside><main>{pages[tab]}</main>{toast && <div className={`toast ${toast.error ? 'error-toast' : ''}`}>{toast.message}</div>}</div>
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
