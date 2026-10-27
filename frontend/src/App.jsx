import { useCallback, useEffect, useState } from 'react'
import { LogOut, LayoutDashboard, Network, Users, UserCog } from 'lucide-react'
import { api } from './api.js'
import { useRealtime } from './useRealtime.js'
import Login from './pages/Login.jsx'
import ChangePassword from './pages/ChangePassword.jsx'
import Dashboard from './pages/Dashboard.jsx'
import NodesPage from './pages/NodesPage.jsx'
import UsersPage from './pages/UsersPage.jsx'

function upsert(list, item) {
  const i = list.findIndex((x) => x.id === item.id)
  if (i === -1) return [item, ...list]
  const copy = list.slice()
  copy[i] = item
  return copy
}

export default function App() {
  const [me, setMe] = useState(undefined) // undefined = cargando, null = sin sesión
  const [page, setPage] = useState('dashboard')
  const [nodes, setNodes] = useState([])
  const [jobs, setJobs] = useState([])
  const [catalog, setCatalog] = useState([])
  const [logEvents, setLogEvents] = useState([])

  useEffect(() => {
    api.get('/api/auth/me').then(setMe).catch(() => setMe(null))
  }, [])

  const ready = Boolean(me && !me.must_change_password)

  const reload = useCallback(async () => {
    const [n, j, c] = await Promise.all([api.get('/api/nodes'), api.get('/api/jobs?limit=200'), api.get('/api/catalog')])
    setNodes(n)
    setJobs(j)
    setCatalog(c)
  }, [])

  useEffect(() => {
    if (ready) reload().catch(() => {})
  }, [ready, reload])

  const onMessage = useCallback((msg) => {
    switch (msg.type) {
      case 'node.update':
        setNodes((list) => upsert(list, msg.node).sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name)))
        break
      case 'node.removed':
        setNodes((list) => list.filter((n) => n.id !== msg.id))
        break
      case 'job.update':
        setJobs((list) => upsert(list, msg.job))
        break
      case 'job.removed':
        setJobs((list) => list.filter((j) => j.id !== msg.id))
        break
      case 'job.log':
        setLogEvents((list) => [...list.slice(-500), msg])
        break
      default:
    }
  }, [])

  const connected = useRealtime(ready, onMessage, () => reload().catch(() => {}))

  const logout = async () => {
    await api.post('/api/auth/logout').catch(() => {})
    setMe(null)
    setNodes([])
    setJobs([])
    setPage('dashboard')
  }

  if (me === undefined) return <div className="center-screen muted">Cargando…</div>
  if (me === null) return <Login onLogin={setMe} />
  if (me.must_change_password) return <ChangePassword me={me} onDone={setMe} onLogout={logout} forced />

  const nav = [
    { id: 'dashboard', label: 'Panel', icon: LayoutDashboard },
    { id: 'nodes', label: 'Nodos', icon: Network },
    ...(me.role === 'admin' ? [{ id: 'users', label: 'Usuarios', icon: Users }] : []),
    { id: 'account', label: 'Cuenta', icon: UserCog },
  ]

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-logo">S</span>
          <span>Snack-Drop</span>
        </div>
        <nav className="nav">
          {nav.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-btn ${page === id ? 'active' : ''}`} onClick={() => setPage(id)}>
              <Icon size={16} /> {label}
            </button>
          ))}
        </nav>
        <div className="topbar-right">
          <span className={`conn ${connected ? 'ok' : ''}`}>
            <span className="dot" /> {connected ? 'Conectado' : 'Reconectando…'}
          </span>
          <span className="muted small">{me.username}</span>
          <button className="icon-btn" title="Cerrar sesión" onClick={logout}>
            <LogOut size={16} />
          </button>
        </div>
      </header>
      <main className="content">
        {page === 'dashboard' && (
          <Dashboard me={me} nodes={nodes} jobs={jobs} catalog={catalog} logEvents={logEvents} onOpenNodes={() => setPage('nodes')} />
        )}
        {page === 'nodes' && <NodesPage me={me} nodes={nodes} onChanged={reload} />}
        {page === 'users' && me.role === 'admin' && <UsersPage me={me} />}
        {page === 'account' && <ChangePassword me={me} onDone={setMe} />}
      </main>
    </div>
  )
}
