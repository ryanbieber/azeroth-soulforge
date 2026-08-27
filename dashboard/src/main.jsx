import { StrictMode, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './skill.css'

const CLASS_NAMES = {1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'}
const RACE_NAMES = {1:'Human',2:'Orc',3:'Dwarf',4:'Night Elf',5:'Undead',6:'Tauren',7:'Gnome',8:'Troll',10:'Blood Elf',11:'Draenei'}

async function api(path, options = {}, csrf = '') {
  const method = options.method || 'GET'
  const headers = { ...(options.headers || {}) }
  if (options.body && typeof options.body !== 'string') {
    headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(options.body)
  }
  if (!['GET', 'HEAD'].includes(method) && csrf) headers['X-CSRF-Token'] = csrf
  const response = await fetch(path, { credentials: 'same-origin', ...options, method, headers })
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw Object.assign(new Error(data.detail || data.error || `Request failed (${response.status})`), { status: response.status })
  return data
}

function Login({ onLogin }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const session = await api('/admin/v1/session', { method:'POST', body:{ password } })
      onLogin(session.csrf_token)
    } catch (reason) { setError(reason.message) } finally { setBusy(false) }
  }
  return <main className="login-shell">
    <section className="login-card">
      <div className="sigil">SF</div>
      <p className="eyebrow">Azeroth operations</p>
      <h1>Enter the Soulforge</h1>
      <p className="muted">Manage your realm and its persistent companions from your trusted home network.</p>
      <form onSubmit={submit}>
        <label>Admin password<input autoFocus type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        <button className="primary wide" disabled={busy || !password}>{busy ? 'Unlocking…' : 'Unlock forge'}</button>
      </form>
    </section>
  </main>
}

function StatusPill({ service }) {
  const healthy = service.running && (!service.health || service.health === 'healthy')
  return <div className="service-row"><span className={`dot ${healthy?'online':'offline'}`} /><div><strong>{service.service.replace('ac-','')}</strong><small>{service.health || service.status}</small></div></div>
}

function Overview({ csrf, notify }) {
  const [status, setStatus] = useState({ services:[] })
  const [busy, setBusy] = useState('')
  const load = () => api('/admin/v1/server/status').then(setStatus).catch(e=>notify(e.message, true))
  useEffect(() => { load(); const timer=setInterval(load,10000); return()=>clearInterval(timer) }, [])
  async function action(name) {
    setBusy(name)
    try { await api(`/admin/v1/server/actions/${name}`, {method:'POST'}, csrf); notify(`Game servers ${name} command completed`); await load() }
    catch(e){notify(e.message,true)} finally{setBusy('')}
  }
  const gameOnline = status.services.filter(s=>['ac-worldserver','ac-authserver'].includes(s.service)).every(s=>s.running)
  return <div className="page">
    <header className="page-head"><div><p className="eyebrow">Realm command</p><h2>Server overview</h2></div><span className={`realm-state ${gameOnline?'up':'down'}`}>{gameOnline?'Realm online':'Realm offline'}</span></header>
    <section className="hero-panel"><div><span className="kicker">Azeroth Soulforge</span><h3>Your world, one command away.</h3><p>Stop gameplay for maintenance while this control plane remains available.</p></div>
      <div className="actions"><button className="primary" disabled={!!busy} onClick={()=>action('start')}>Start game</button><button disabled={!!busy} onClick={()=>action('restart')}>Restart</button><button className="danger" disabled={!!busy} onClick={()=>action('stop')}>Stop game</button></div>
    </section>
    <section className="panel"><div className="section-title"><h3>Stack health</h3><span>Refreshes every 10 seconds</span></div><div className="service-grid">{status.services.map(service=><StatusPill key={service.service} service={service}/>)}</div></section>
    <section className="notice"><strong>Safety boundary</strong><p>Souls can speak and remember. Playerbots alone controls combat, movement, inventory, quests, and groups.</p></section>
  </div>
}

function Bots({ csrf, notify, souls, refreshSouls }) {
  const [bots, setBots] = useState([]), [search,setSearch]=useState(''), [busy,setBusy]=useState('')
  useEffect(()=>{api('/admin/v1/bots').then(x=>setBots(x.bots)).catch(e=>notify(e.message,true))},[])
  const soulKeys = useMemo(()=>new Set(souls.map(s=>`${s.realm_id}:${s.bot_guid}`)),[souls])
  const shown = bots.filter(b=>`${b.name} ${CLASS_NAMES[b.class]||''}`.toLowerCase().includes(search.toLowerCase()))
  async function forge(bot){setBusy(bot.guid);try{await api('/admin/v1/souls',{method:'POST',body:{realm_id:'azeroth-soulforge',bot_guid:bot.guid,name:bot.name}},csrf);notify(`${bot.name}'s soul is ready`);refreshSouls()}catch(e){notify(e.message,true)}finally{setBusy('')}}
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Playerbot roster</p><h2>All companions</h2></div><span className="count">{bots.length} bots</span></header>
    <div className="toolbar"><input placeholder="Search name or class…" value={search} onChange={e=>setSearch(e.target.value)}/></div>
    {!bots.length && <section className="empty"><h3>No generated bots yet</h3><p>Playerbots creates its roster after the worldserver completes its first startup.</p></section>}
    <div className="bot-grid">{shown.map(bot=>{const forged=soulKeys.has(`azeroth-soulforge:${bot.guid}`);return <article className="bot-card" key={bot.guid}><div className={`portrait class-${bot.class}`}>{bot.name.slice(0,1)}</div><div className="bot-main"><div className="bot-title"><h3>{bot.name}</h3><span className={bot.online?'online-text':'muted'}>{bot.online?'Online':'Offline'}</span></div><p>Level {bot.level} {RACE_NAMES[bot.race]||'Unknown'} {CLASS_NAMES[bot.class]||'Adventurer'}</p></div><button className={forged?'quiet':'primary'} disabled={forged||busy===bot.guid} onClick={()=>forge(bot)}>{forged?'Soul forged':'Forge soul'}</button></article>})}</div>
  </div>
}

function SoulEditor({ soul, csrf, close, saved, notify }) {
  const [form,setForm]=useState({...soul,enabled:Boolean(soul.enabled)}), [memories,setMemories]=useState([]), [skill,setSkill]=useState(''), [busy,setBusy]=useState(false)
  const memoryPath=`/admin/v1/souls/${encodeURIComponent(soul.realm_id)}/${soul.bot_guid}/memories`
  const skillPath=`/admin/v1/souls/${encodeURIComponent(soul.realm_id)}/${soul.bot_guid}/skill`
  useEffect(()=>{Promise.all([api(memoryPath),api(skillPath)]).then(([memoryData,skillData])=>{setMemories(memoryData.memories);setSkill(skillData.document)}).catch(e=>notify(e.message,true))},[])
  const update=(key,value)=>setForm({...form,[key]:value})
  async function save(){setBusy(true);try{await Promise.all([api(`/admin/v1/souls/${encodeURIComponent(soul.realm_id)}/${soul.bot_guid}`,{method:'PATCH',body:{archetype:form.archetype,voice:form.voice,values_text:form.values_text,enabled:form.enabled}},csrf),api(skillPath,{method:'PUT',body:{document:skill}},csrf)]);notify(`${soul.name}'s profile and SKILL.md saved`);saved();close()}catch(e){notify(e.message,true)}finally{setBusy(false)}}
  async function forget(id){if(!confirm('Permanently delete this memory?'))return;try{await api(`${memoryPath}/${id}`,{method:'DELETE'},csrf);setMemories(memories.filter(m=>m.id!==id))}catch(e){notify(e.message,true)}}
  return <div className="modal-backdrop" onMouseDown={e=>e.target===e.currentTarget&&close()}><section className="modal"><button className="close" onClick={close}>×</button><p className="eyebrow">Guild companion · {soul.realm_id}</p><h2>{soul.name}</h2><label className="toggle"><input type="checkbox" checked={form.enabled} onChange={e=>update('enabled',e.target.checked)}/><span/>Soul dialogue enabled</label><label>Archetype<textarea value={form.archetype} onChange={e=>update('archetype',e.target.value)}/></label><label>Voice<textarea value={form.voice} onChange={e=>update('voice',e.target.value)}/></label><label>Values<textarea value={form.values_text} onChange={e=>update('values_text',e.target.value)}/></label><label>Character SKILL.md<textarea className="skill-editor" value={skill} onChange={e=>setSkill(e.target.value)} placeholder="History, mannerisms, loyalties, fears, goals, boundaries…"/></label><p className="hint">Soulforge manages the identity header, canonical profile, and memory ledger. This section is yours to shape.</p><button className="primary" disabled={busy||!skill.trim()} onClick={save}>Save soul</button>
    <div className="memory-head"><h3>Memories</h3><span>{memories.length} recent</span></div><div className="memories">{memories.map(m=><article key={m.id}><div><span className={`role ${m.role}`}>{m.role}</span><time>{new Date(m.created_at).toLocaleString()}</time></div><p>{m.text}</p><button className="text-danger" onClick={()=>forget(m.id)}>Forget</button></article>)}{!memories.length&&<p className="muted">No memories recorded yet.</p>}</div></section></div>
}

function Souls({ csrf, notify, souls, refreshSouls }) {
  const [selected,setSelected]=useState(null)
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Persistent identities</p><h2>Forged souls</h2></div><span className="count">{souls.length} souls</span></header>
    {!souls.length&&<section className="empty"><h3>The forge is waiting</h3><p>Forge companions from the Bots page or speak to one in game.</p></section>}
    <div className="soul-grid">{souls.map(s=><button className="soul-card" key={`${s.realm_id}:${s.bot_guid}`} onClick={()=>setSelected(s)}><div className="soul-glow">{s.name.slice(0,1)}</div><div><h3>{s.name}</h3><p>{s.archetype}</p><small>{s.memory_count} memories · {s.enabled?'Active':'Paused'}</small></div></button>)}</div>
    {selected&&<SoulEditor soul={selected} csrf={csrf} close={()=>setSelected(null)} saved={refreshSouls} notify={notify}/>}</div>
}

function Settings({ csrf, notify }) {
  const [form,setForm]=useState(null), [models,setModels]=useState([]), [auctionCharacters,setAuctionCharacters]=useState([]), [newModel,setNewModel]=useState(''), [busy,setBusy]=useState('')
  async function load(){try{const [settings,modelData,auctionData]=await Promise.all([api('/admin/v1/server/settings'),api('/admin/v1/models'),api('/admin/v1/auction-house/characters')]);setForm(settings);setModels(modelData.models);setAuctionCharacters(auctionData.characters)}catch(e){notify(e.message,true)}}
  useEffect(()=>{load()},[])
  const set=(key,value)=>setForm({...form,[key]:value})
  async function save(){setBusy('save');try{const result=await api('/admin/v1/server/settings',{method:'PUT',body:{...form,random_bots:Number(form.random_bots),max_added_bots:Number(form.max_added_bots),player_limit:Number(form.player_limit),xp_rate:Number(form.xp_rate),reputation_rate:Number(form.reputation_rate),loot_rate:Number(form.loot_rate),money_rate:Number(form.money_rate),honor_rate:Number(form.honor_rate),profession_skill_rate:Number(form.profession_skill_rate),auction_house_items_per_cycle:Number(form.auction_house_items_per_cycle),temperature:Number(form.temperature),max_tokens:Number(form.max_tokens)}},csrf);notify(result.world_restarted?'Settings applied; worldserver restarted':'Settings applied')}catch(e){notify(e.message,true)}finally{setBusy('')}}
  async function install(){setBusy('model');try{await api('/admin/v1/models/pull',{method:'POST',body:{model:newModel}},csrf);notify(`${newModel} installed`);setNewModel('');await load()}catch(e){notify(e.message,true)}finally{setBusy('')}}
  if(!form)return <div className="loading">Reading forge settings…</div>
  return <div className="page"><header className="page-head"><div><p className="eyebrow">Validated configuration</p><h2>Server settings</h2></div></header>
    <div className="settings-grid"><section className="panel form-panel"><div className="section-title"><h3>Realm</h3><span>Game settings</span></div><label>Realm name<input value={form.realm_name} onChange={e=>set('realm_name',e.target.value)} maxLength="32"/></label><label>Server type<select value={form.realm_type} onChange={e=>set('realm_type',e.target.value)}><option value="normal">Normal (PvE)</option><option value="pvp">PvP</option><option value="rp">Roleplaying (PvE)</option><option value="rp_pvp">Roleplaying PvP</option></select></label><label>Random bots<input type="number" min="0" max="200" value={form.random_bots} onChange={e=>set('random_bots',e.target.value)}/></label><label>Maximum added companions<input type="number" min="1" max="80" value={form.max_added_bots} onChange={e=>set('max_added_bots',e.target.value)}/></label><label>Player limit<input type="number" min="1" max="1000" value={form.player_limit} onChange={e=>set('player_limit',e.target.value)}/></label><p className="hint">Changing server type or population settings safely restarts the worldserver.</p></section>
      <section className="panel form-panel"><div className="section-title"><h3>Gameplay rates</h3><span>0.1×–10×</span></div><label>Leveling speed<input type="number" min="0.1" max="10" step="0.1" value={form.xp_rate} onChange={e=>set('xp_rate',e.target.value)}/></label><label>Reputation gain<input type="number" min="0.1" max="10" step="0.1" value={form.reputation_rate} onChange={e=>set('reputation_rate',e.target.value)}/></label><label>Item loot<input type="number" min="0.1" max="10" step="0.1" value={form.loot_rate} onChange={e=>set('loot_rate',e.target.value)}/></label><label>Money drops<input type="number" min="0.1" max="10" step="0.1" value={form.money_rate} onChange={e=>set('money_rate',e.target.value)}/></label><label>Honor gain<input type="number" min="0.1" max="10" step="0.1" value={form.honor_rate} onChange={e=>set('honor_rate',e.target.value)}/></label><label>Profession skill gain<input type="number" min="1" max="10" step="1" value={form.profession_skill_rate} onChange={e=>set('profession_skill_rate',e.target.value)}/></label><p className="hint">Rates are multipliers. For example, 3 means three times the normal rate.</p></section>
      <section className="panel form-panel"><div className="section-title"><h3>Auction house</h3><span>Official AHBot</span></div><label>Dedicated auctioneer<select value={form.auction_house_character_guid} onChange={e=>set('auction_house_character_guid',e.target.value)}><option value="0">Choose an unused character…</option>{auctionCharacters.map(character=><option key={character.guid} value={character.guid}>{character.name} · {character.account}{character.online?' · online':''}</option>)}</select></label><label className="toggle"><input type="checkbox" checked={form.auction_house_seller} onChange={e=>set('auction_house_seller',e.target.checked)}/><span/>Populate auctions with items</label><label className="toggle"><input type="checkbox" checked={form.auction_house_buyer} onChange={e=>set('auction_house_buyer',e.target.checked)}/><span/>Bid on player auctions</label><label>Items processed per cycle<input type="number" min="1" max="1000" step="1" value={form.auction_house_items_per_cycle} onChange={e=>set('auction_house_items_per_cycle',e.target.value)}/></label><p className="hint">Create an unused alt in the WoW client, log it out, then select it here. Do not play a character while it is assigned as the auctioneer.</p></section>
      <section className="panel form-panel"><div className="section-title"><h3>Local intelligence</h3><span>Ollama</span></div><label>Active model<select value={form.chat_model} onChange={e=>set('chat_model',e.target.value)}>{models.map(model=><option key={model}>{model}</option>)}</select></label><label>Creativity <output>{form.temperature}</output><input type="range" min="0" max="2" step="0.05" value={form.temperature} onChange={e=>set('temperature',e.target.value)}/></label><label>Reply token limit<input type="number" min="32" max="512" value={form.max_tokens} onChange={e=>set('max_tokens',e.target.value)}/></label><label className="toggle"><input type="checkbox" checked={form.souls_enabled} onChange={e=>set('souls_enabled',e.target.checked)}/><span/>Soul dialogue enabled globally</label><div className="model-install"><input placeholder="e.g. qwen3.5:9b" value={newModel} onChange={e=>setNewModel(e.target.value)}/><button disabled={!newModel||!!busy} onClick={install}>{busy==='model'?'Installing…':'Install model'}</button></div><p className="hint">Model downloads can be several gigabytes and may take time.</p></section></div>
    <button className="primary save-settings" disabled={!!busy} onClick={save}>{busy==='save'?'Applying…':'Apply settings'}</button>
    <section className="notice warning"><strong>Progression is deliberately locked</strong><p>Phase unlocks are not exposed until automatic backup verification and restore testing are implemented.</p></section>
  </div>
}

function App() {
  const [csrf,setCsrf]=useState(null), [checking,setChecking]=useState(true), [tab,setTab]=useState('overview'), [souls,setSouls]=useState([]), [toast,setToast]=useState(null)
  const notify=(message,error=false)=>{setToast({message,error});setTimeout(()=>setToast(null),4500)}
  const refreshSouls=()=>api('/admin/v1/souls').then(x=>setSouls(x.souls)).catch(()=>{})
  useEffect(()=>{api('/admin/v1/session').then(x=>setCsrf(x.csrf_token)).catch(()=>{}).finally(()=>setChecking(false))},[])
  useEffect(()=>{if(csrf)refreshSouls()},[csrf])
  async function logout(){try{await api('/admin/v1/session',{method:'DELETE'},csrf)}finally{setCsrf(null)}}
  if(checking)return <div className="loading full">Lighting the forge…</div>
  if(!csrf)return <Login onLogin={setCsrf}/>
  const pages={overview:<Overview csrf={csrf} notify={notify}/>,bots:<Bots csrf={csrf} notify={notify} souls={souls} refreshSouls={refreshSouls}/>,souls:<Souls csrf={csrf} notify={notify} souls={souls} refreshSouls={refreshSouls}/>,settings:<Settings csrf={csrf} notify={notify}/>}
  return <div className="app-shell"><aside><div className="brand"><div className="sigil small">SF</div><div><strong>Soulforge</strong><small>Azeroth control</small></div></div><nav>{[['overview','Overview'],['bots','All bots'],['souls','Souls'],['settings','Settings']].map(([key,label])=><button className={tab===key?'active':''} key={key} onClick={()=>setTab(key)}><span>{key==='overview'?'⌁':key==='bots'?'♟':key==='souls'?'✦':'⚙'}</span>{label}</button>)}</nav><button className="logout" onClick={logout}>Lock dashboard</button></aside><main className="content">{pages[tab]}</main>{toast&&<div className={`toast ${toast.error?'bad':''}`}>{toast.message}</div>}</div>
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
