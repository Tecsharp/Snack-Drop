import { useCallback, useEffect, useRef, useState } from 'react'
import { History, Home, LogOut, Monitor, Settings, Users } from 'lucide-react'
import { api } from './api.js'
import { useAppearance } from './appearance.js'
import { isActive } from './format.js'
import { useRealtime } from './useRealtime.js'
import { initials, nodeState, ToastProvider, useToast } from './ui.jsx'
import Login from './pages/Login.jsx'
import ChangePassword from './pages/ChangePassword.jsx'
import Dashboard from './pages/Dashboard.jsx'
import JobsPage from './pages/JobsPage.jsx'
import NodesPage from './pages/NodesPage.jsx'
import UsersPage from './pages/UsersPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'

function upsert(list, item) {
  const i = list.findIndex((x) => x.id === item.id)
  if (i === -1) return [item, ...list]
  const copy = list.slice()
  copy[i] = item
  return copy
}

const PAGES = {
  home: { title: 'Inicio', icon: Home },
  jobs: { title: 'Trabajos', icon: History },
  nodes: { title: 'Computadoras', icon: Monitor },
  users: { title: 'Usuarios', icon: Users, admin: true },
  settings: { title: 'Ajustes', icon: Settings },
}

function Shell() {
  const [me, setMe] = useState(undefined) // undefined = cargando, null = sin sesión
  const [page, setPage] = useState(() => (location.hash.slice(1) in PAGES ? location.hash.slice(1) : 'home'))
  const [nodes, setNodes] = useState([])
  const [jobs, setJobs] = useState([])
  const [catalog, setCatalog] = useState([])
  const [logEvents, setLogEvents] = useState([])
  const [appearance, setAppearance] = useAppearance()
  const toast = useToast()
  const jobsRef = useRef(jobs)
  jobsRef.current = jobs

  useEffect(() => {
    api.get('/api/auth/me').then(setMe).catch(() => setMe(null))
  }, [])

  useEffect(() => {
    const onHash = () => location.hash.slice(1) in PAGES && setPage(location.hash.slice(1))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = (id) => {
    setPage(id)
    history.replaceState(null, '', `#${id}`)
    window.scrollTo({ top: 0 })
  }

  const ready = Boolean(me && !me.must_change_password)

  const reload = useCallback(async () => {
    const [n, j, c] = await Promise.all([api.get('/api/nodes'), api.get('/api/jobs?limit=300'), api.get('/api/catalog')])
    setNodes(n)
    setJobs(j)
    setCatalog(c)
  }, [])

  useEffect(() => {
    if (ready) reload().catch(() => {})
  }, [ready, reload])

  const onMessage = useCallback(
    (msg) => {
      switch (msg.type) {
        case 'node.update':
          setNodes((list) => upsert(list, msg.node).sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name)))
          break
        case 'node.removed':
          setNodes((list) => list.filter((n) => n.id !== msg.id))
          break
        case 'job.update': {
          const prev = jobsRef.current.find((j) => j.id === msg.job.id)
          if (prev && isActive(prev) && !isActive(msg.job) && msg.job.owner_id === me?.id) {
            if (msg.job.status === 'done') toast({ tone: 'success', title: 'Trabajo listo', body: msg.job.title })
            if (msg.job.status === 'failed') toast({ tone: 'error', title: 'El trabajo falló', body: msg.job.title })
          }
          setJobs((list) => upsert(list, msg.job))
          break
        }
        case 'job.removed':
          setJobs((list) => list.filter((j) => j.id !== msg.id))
          break
        case 'job.log':
          setLogEvents((list) => [...list.slice(-500), msg])
          break
        default:
      }
    },
    [me?.id, toast],
  )

  const connected = useRealtime(ready, onMessage, () => reload().catch(() => {}))

  const logout = async () => {
    await api.post('/api/auth/logout').catch(() => {})
    setMe(null)
    setNodes([])
    setJobs([])
    go('home')
  }

  if (me === undefined) return <div className="center-screen muted">Cargando…</div>
  if (me === null) return <Login onLogin={setMe} />
  if (me.must_change_password) return <ChangePassword me={me} onDone={setMe} onLogout={logout} forced />

  const nav = Object.entries(PAGES).filter(([, p]) => !p.admin || me.role === 'admin')
  const active = jobs.filter(isActive).length
  const online = nodes.filter((n) => n.online).length
  const current = PAGES[page] && (!PAGES[page].admin || me.role === 'admin') ? page : 'home'

  const common = { me, nodes, jobs, catalog, logEvents, go, reload, connected }

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Navegación">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">S</span>
          Snack-Drop
        </div>
        <nav>
          {nav.map(([id, p]) => (
            <button key={id} className="nav-item" aria-current={current === id ? 'page' : undefined} onClick={() => go(id)}>
              <p.icon size={17} aria-hidden="true" />
              {p.title}
              {id === 'jobs' && active > 0 && <span className="count">{active}</span>}
              {id === 'nodes' && <span className="count">{online}/{nodes.length}</span>}
            </button>
          ))}
        </nav>
        {nodes.length > 0 && (
          <>
            <div className="sidebar-section">Computadoras</div>
            <div className="sidebar-nodes">
              {nodes.map((n) => (
                <div key={n.id} className="sidebar-node" title={nodeState(n).label}>
                  <span className={`dot ${nodeState(n).dot}`} aria-hidden="true" />
                  <span className="truncate grow">{n.name}</span>
                  <span className="caption">{nodeState(n).label}</span>
                </div>
              ))}
            </div>
          </>
        )}
        <div className="sidebar-footer">
          <span className={`conn ${connected ? 'ok' : ''}`} style={{ padding: '0 4px' }}>
            <span className="dot" aria-hidden="true" /> {connected ? 'Conectado en tiempo real' : 'Reconectando…'}
          </span>
          <div className="user-chip">
            <span className="avatar" aria-hidden="true">{initials(me.username)}</span>
            <div className="grow">
              <div className="small truncate" style={{ fontWeight: 600 }}>{me.username}</div>
              <div className="caption">{me.role === 'admin' ? 'Administrador' : 'Usuario'}</div>
            </div>
            <button className="icon-btn" onClick={logout} aria-label="Cerrar sesión" title="Cerrar sesión">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <div className="main">
        {current === 'home' && <Dashboard {...common} />}
        {current === 'jobs' && <JobsPage {...common} />}
        {current === 'nodes' && <NodesPage {...common} />}
        {current === 'users' && <UsersPage me={me} />}
        {current === 'settings' && (
          <SettingsPage me={me} onMe={setMe} appearance={appearance} setAppearance={setAppearance} onLogout={logout} />
        )}
      </div>

      <nav className="tabbar" aria-label="Navegación">
        {nav.map(([id, p]) => (
          <button key={id} className="tab" aria-current={current === id ? 'page' : undefined} onClick={() => go(id)}>
            <p.icon size={22} aria-hidden="true" />
            {p.title}
          </button>
        ))}
      </nav>
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  )
}
