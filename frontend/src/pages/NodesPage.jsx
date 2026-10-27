import { useState } from 'react'
import { Check, ChevronRight, Copy, Cpu, KeyRound, Laptop, Monitor, Plus, Trash2, UserPlus, X } from 'lucide-react'
import { api } from '../api.js'
import Toolbar from '../components/Toolbar.jsx'
import { formatDate } from '../format.js'
import { Alert, Empty, nodeState, Sheet, Toggle } from '../ui.jsx'

function CopyField({ label, value }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="field">
      <span>{label}</span>
      <div className="copy-field">
        <code>{value}</code>
        <button
          type="button"
          className="icon-btn"
          aria-label={`Copiar ${label}`}
          onClick={() => {
            navigator.clipboard?.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          {copied ? <Check size={15} /> : <Copy size={15} />}
        </button>
      </div>
    </div>
  )
}

function InstallSheet({ info, onClose }) {
  return (
    <Sheet title="Conecta la computadora" onClose={onClose} wide footer={<button className="btn primary" onClick={onClose}>Listo</button>}>
      <Alert tone="warn">Guarda este token ahora: no se volverá a mostrar. Quien lo tenga puede recibir trabajos como esta computadora.</Alert>
      <p className="small" style={{ margin: 0 }}>
        En esa computadora, descarga este proyecto y ejecuta <b>uno</b> de estos comandos:
      </p>
      <CopyField label="Con Docker (recomendado)" value={info.docker_command} />
      <CopyField label="Sin Docker, con Python 3.11+ en la carpeta worker/" value={info.python_command} />
      <CopyField label="Token" value={info.token} />
      <p className="caption" style={{ margin: 0 }}>
        La computadora solo abre una conexión de salida hacia este servidor: no expone puertos ni su escritorio. Aparecerá como
        «Disponible» en cuanto se conecte.
      </p>
    </Sheet>
  )
}

function AddNodeSheet({ onClose, onCreated }) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const create = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onCreated(await api.post('/api/nodes', { name }))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Sheet
      title="Agregar computadora"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" form="add-node" disabled={!name.trim() || busy}>Crear</button>
        </>
      }
    >
      <form id="add-node" className="stack" onSubmit={create}>
        <label className="field">
          Nombre
          <input autoFocus placeholder="Por ejemplo: PC del estudio" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} />
        </label>
        <p className="caption" style={{ margin: 0 }}>
          La computadora será tuya: tú decides quién más puede usarla y puedes pausarla o desconectarla cuando quieras.
        </p>
        {error && <Alert tone="error">{error}</Alert>}
      </form>
    </Sheet>
  )
}

function NodeSheet({ node, me, catalog, onClose, onInstall, onChanged }) {
  const [name, setName] = useState(node.name)
  const [grantUser, setGrantUser] = useState('')
  const [error, setError] = useState('')
  const s = nodeState(node)

  const run = async (fn) => {
    setError('')
    try {
      await fn()
      await onChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  const details = [
    ['Estado', s.label],
    ['Equipo', [node.hostname, node.os, node.arch].filter(Boolean).join(' · ') || '—'],
    ['Aceleración', [node.accelerator, node.hw_encoders?.length ? node.hw_encoders.join(', ') : null].filter(Boolean).join(' · ') || '—'],
    ['Dueño', node.owner],
    ['Última conexión', formatDate(node.last_seen)],
    ['Trabajos', `${node.jobs_done} hechos · ${node.jobs_failed} fallidos`],
  ]

  return (
    <Sheet title={node.name} onClose={onClose} wide>
      <div className="group">
        {details.map(([k, v]) => (
          <div key={k} className="list-row" style={{ minHeight: 44 }}>
            <span className="grow secondary">{k}</span>
            <span className="small" style={{ textAlign: 'right' }}>{v}</span>
          </div>
        ))}
      </div>

      <div className="stack" style={{ gap: 8 }}>
        <b className="small">Puede hacer {node.capabilities.length} de {catalog.length} operaciones</b>
        {node.capabilities.length === 0 && <span className="caption">Se conocerán cuando se conecte.</span>}
        {[...new Set(catalog.map((c) => c.category))].map((cat) => {
          const ops = catalog.filter((c) => c.category === cat)
          const can = ops.filter((c) => node.capabilities.includes(c.id))
          if (!node.capabilities.length) return null
          return (
            <div key={cat} className="stack" style={{ gap: 4 }}>
              <span className="caption">{cat} · {can.length}/{ops.length}</span>
              <div className="chips">
                {ops.map((c) => (
                  <span key={c.id} className={`pill ${node.capabilities.includes(c.id) ? 'green' : ''}`} title={c.requires || c.description}>
                    {c.title}
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {node.can_manage && (
        <>
          <div className="group">
            <div className="list-row">
              <input aria-label="Nombre de la computadora" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} />
              <button className="btn" disabled={!name.trim() || name === node.name} onClick={() => run(() => api.patch(`/api/nodes/${node.id}`, { name }))}>
                Renombrar
              </button>
            </div>
            <div className="list-row">
              <div className="grow">
                <Toggle
                  label="Aceptar trabajos"
                  help="Desactívalo para pausar esta computadora sin desconectarla"
                  checked={!node.is_paused}
                  onChange={(v) => run(() => api.patch(`/api/nodes/${node.id}`, { is_paused: !v }))}
                />
              </div>
            </div>
            {me.role === 'admin' && (
              <div className="list-row">
                <div className="grow">
                  <Toggle
                    label="Disponible para todos los usuarios"
                    checked={node.shared_with_all}
                    onChange={(v) => run(() => api.patch(`/api/nodes/${node.id}`, { shared_with_all: v }))}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="stack" style={{ gap: 8 }}>
            <b className="small">Personas autorizadas</b>
            <div className="chips">
              {(node.grants || []).length === 0 && <span className="caption">Solo tú{node.shared_with_all ? ' y todos los usuarios' : ''}.</span>}
              {(node.grants || []).map((g) => (
                <span key={g.user_id} className="chip">
                  {g.username}
                  <button aria-label={`Quitar acceso a ${g.username}`} onClick={() => run(() => api.del(`/api/nodes/${node.id}/grants/${g.user_id}`))}>
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault()
                run(async () => {
                  await api.post(`/api/nodes/${node.id}/grants`, { username: grantUser })
                  setGrantUser('')
                })
              }}
            >
              <input placeholder="Nombre de usuario" value={grantUser} onChange={(e) => setGrantUser(e.target.value)} aria-label="Autorizar usuario" />
              <button className="btn" disabled={!grantUser.trim()}>
                <UserPlus size={15} aria-hidden="true" /> Autorizar
              </button>
            </form>
          </div>

          <div className="row wrap">
            <button className="btn" onClick={() => run(async () => onInstall((await api.post(`/api/nodes/${node.id}/rotate-token`)).install))}>
              <KeyRound size={15} aria-hidden="true" /> Generar token nuevo
            </button>
            {node.kind !== 'master' && (
              <button
                className="btn destructive"
                style={{ marginLeft: 'auto' }}
                onClick={() =>
                  window.confirm(`¿Eliminar «${node.name}»? Dejará de recibir trabajos y su token dejará de funcionar.`) &&
                  run(async () => {
                    await api.del(`/api/nodes/${node.id}`)
                    onClose()
                  })
                }
              >
                <Trash2 size={15} aria-hidden="true" /> Eliminar
              </button>
            )}
          </div>
        </>
      )}
      {error && <Alert tone="error">{error}</Alert>}
    </Sheet>
  )
}

export default function NodesPage({ me, nodes, catalog, reload }) {
  const [adding, setAdding] = useState(false)
  const [install, setInstall] = useState(null)
  const [selected, setSelected] = useState(null)
  const node = nodes.find((n) => n.id === selected)

  const mine = nodes.filter((n) => n.can_manage)
  const shared = nodes.filter((n) => !n.can_manage)

  const row = (n) => {
    const s = nodeState(n)
    const Glyph = n.kind === 'master' ? Monitor : n.os === 'macOS' ? Laptop : Cpu
    return (
      <button key={n.id} className="list-row clickable" onClick={() => setSelected(n.id)}>
        <span className="node-glyph" aria-hidden="true">
          <Glyph size={18} />
        </span>
        <span className="grow">
          <span className="row" style={{ gap: 6 }}>
            <span className="title truncate">{n.name}</span>
            {n.kind === 'master' && <span className="pill">servidor</span>}
            {n.gpu && <span className="pill accent">GPU</span>}
          </span>
          <span className="caption row" style={{ gap: 6 }}>
            <span className={`dot ${s.dot}`} aria-hidden="true" />
            {s.label}
            {n.current_job ? ` · ${n.current_job.title}` : ''}
            <span className="hide-compact">· {[n.os, n.accelerator].filter(Boolean).join(' · ') || 'sin conectar aún'}</span>
          </span>
        </span>
        <span className="caption hide-compact tnum">{n.capabilities.length} operaciones</span>
        <ChevronRight size={16} className="muted" aria-hidden="true" />
      </button>
    )
  }

  return (
    <>
      <Toolbar title="Computadoras" subtitle={`${nodes.filter((n) => n.online).length} de ${nodes.length} disponibles`}>
        <button className="btn primary" onClick={() => setAdding(true)}>
          <Plus size={16} aria-hidden="true" /> Agregar
        </button>
      </Toolbar>
      <div className="page">
        <section className="section">
          <div className="section-head">
            <h2>Mis computadoras</h2>
          </div>
          <div className="group">
            {mine.length ? mine.map(row) : <Empty icon={Monitor} title="Sin computadoras propias">Agrega una para repartir trabajo.</Empty>}
          </div>
          <p className="footnote">Toca una computadora para pausarla, renombrarla o autorizar a otras personas.</p>
        </section>
        {shared.length > 0 && (
          <section className="section">
            <div className="section-head">
              <h2>Compartidas contigo</h2>
            </div>
            <div className="group">{shared.map(row)}</div>
            <p className="footnote">Sus dueños te autorizaron a enviarles trabajos. Ellos conservan el control.</p>
          </section>
        )}
      </div>
      {adding && (
        <AddNodeSheet
          onClose={() => setAdding(false)}
          onCreated={async (res) => {
            setAdding(false)
            setInstall(res.install)
            await reload()
          }}
        />
      )}
      {node && !install && <NodeSheet node={node} me={me} catalog={catalog} onClose={() => setSelected(null)} onInstall={setInstall} onChanged={reload} />}
      {install && <InstallSheet info={install} onClose={() => setInstall(null)} />}
    </>
  )
}
