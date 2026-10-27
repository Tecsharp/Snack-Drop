import { useState } from 'react'
import { Copy, KeyRound, Plus, Trash2, UserPlus, X } from 'lucide-react'
import { api } from '../api.js'
import { formatDate, statusLabel } from '../format.js'
import Modal from '../components/Modal.jsx'

function CopyField({ label, value }) {
  const [copied, setCopied] = useState(false)
  return (
    <label>
      {label}
      <div className="copy-field">
        <code>{value}</code>
        <button
          type="button"
          className="icon-btn"
          title="Copiar"
          onClick={() => {
            navigator.clipboard?.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          <Copy size={14} />
        </button>
      </div>
      {copied && <span className="small ok-text">Copiado</span>}
    </label>
  )
}

function InstallModal({ info, onClose }) {
  return (
    <Modal title="Conectar computadora" onClose={onClose} wide>
      <div className="alert warn small">
        Guarda este token ahora: no se volverá a mostrar. Quien lo tenga puede recibir trabajos como este nodo.
      </div>
      <p className="small">
        En la computadora ejecutora, clona este repositorio y ejecuta (requiere Docker):
      </p>
      <CopyField label="Con Docker" value={info.docker_command} />
      <p className="small muted">O sin Docker, con Python 3.11+ dentro de la carpeta <code>worker/</code> tras <code>pip install -r requirements.txt</code>:</p>
      <CopyField label="Con Python" value={info.python_command} />
      <CopyField label="Token" value={info.token} />
      <p className="small muted">
        El agente solo abre una conexión saliente hacia el servidor; no expone puertos ni el escritorio de esa computadora.
      </p>
    </Modal>
  )
}

function NodeRow({ node, me, onInstall, onChanged }) {
  const [grantUser, setGrantUser] = useState('')
  const [error, setError] = useState('')
  const [name, setName] = useState(node.name)

  const run = async (fn) => {
    setError('')
    try {
      await fn()
      await onChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className={`node-row state-${node.state}`}>
      <div className="row space wrap">
        <div>
          <div className="node-name">
            <span className="dot" /> {node.name} <span className="pill">{node.kind}</span>
          </div>
          <div className="muted small">
            {statusLabel(node.state)} · {[node.hostname, node.os, node.arch, node.accelerator].filter(Boolean).join(' · ') || 'nunca conectado'}
          </div>
          <div className="muted small">
            Dueño: {node.owner} · Última conexión: {formatDate(node.last_seen)} · Capacidades:{' '}
            {node.capabilities.length ? node.capabilities.join(', ') : '—'}
          </div>
        </div>
        {node.can_manage && (
          <div className="row gap wrap">
            <button className="btn outline" onClick={() => run(async () => onInstall((await api.post(`/api/nodes/${node.id}/rotate-token`)).install))}>
              <KeyRound size={14} /> Nuevo token
            </button>
            {node.kind !== 'master' && (
              <button
                className="btn outline danger"
                onClick={() => window.confirm(`¿Eliminar el nodo ${node.name}?`) && run(() => api.del(`/api/nodes/${node.id}`))}
              >
                <Trash2 size={14} /> Eliminar
              </button>
            )}
          </div>
        )}
      </div>

      {node.can_manage && (
        <div className="node-settings">
          <div className="row gap wrap">
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={64} aria-label="Nombre del nodo" />
            <button className="btn outline" disabled={!name.trim() || name === node.name} onClick={() => run(() => api.patch(`/api/nodes/${node.id}`, { name }))}>
              Renombrar
            </button>
            {me.role === 'admin' && (
              <label className="check">
                <input
                  type="checkbox"
                  checked={node.shared_with_all}
                  onChange={(e) => run(() => api.patch(`/api/nodes/${node.id}`, { shared_with_all: e.target.checked }))}
                />{' '}
                Disponible para todos los usuarios
              </label>
            )}
          </div>
          <div className="grants">
            <span className="small muted">Usuarios autorizados:</span>
            {(node.grants || []).length === 0 && <span className="small muted">ninguno</span>}
            {(node.grants || []).map((g) => (
              <span key={g.user_id} className="chip">
                {g.username}
                <button className="chip-x" title="Revocar" onClick={() => run(() => api.del(`/api/nodes/${node.id}/grants/${g.user_id}`))}>
                  <X size={12} />
                </button>
              </span>
            ))}
            <form
              className="row gap"
              onSubmit={(e) => {
                e.preventDefault()
                run(async () => {
                  await api.post(`/api/nodes/${node.id}/grants`, { username: grantUser })
                  setGrantUser('')
                })
              }}
            >
              <input placeholder="usuario" value={grantUser} onChange={(e) => setGrantUser(e.target.value)} aria-label="Autorizar usuario" />
              <button className="btn outline" disabled={!grantUser.trim()}>
                <UserPlus size={14} /> Autorizar
              </button>
            </form>
          </div>
        </div>
      )}
      {error && <div className="alert error small">{error}</div>}
    </div>
  )
}

export default function NodesPage({ me, nodes, onChanged }) {
  const [name, setName] = useState('')
  const [install, setInstall] = useState(null)
  const [error, setError] = useState('')

  const create = async (e) => {
    e.preventDefault()
    setError('')
    try {
      const res = await api.post('/api/nodes', { name })
      setName('')
      setInstall(res.install)
      await onChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div className="panel-title">
            <Plus size={18} /> Agregar computadora
          </div>
        </div>
        <form className="row gap wrap pad" onSubmit={create}>
          <input placeholder="Nombre, p. ej. SHRIMPDADDY" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} required />
          <button className="btn primary">Crear nodo y token</button>
        </form>
        <p className="muted small pad">
          Cada nodo pertenece a quien lo crea. Para que otra persona use tu computadora, autoriza su usuario abajo; tú
          conservas el control (pausar, revocar, eliminar).
        </p>
        {error && <div className="alert error small">{error}</div>}
      </section>
      <section className="panel">
        <div className="panel-head">
          <div className="panel-title">Nodos ({nodes.length})</div>
        </div>
        <div className="job-list">
          {nodes.map((n) => (
            <NodeRow key={n.id} node={n} me={me} onInstall={setInstall} onChanged={onChanged} />
          ))}
        </div>
      </section>
      {install && <InstallModal info={install} onClose={() => setInstall(null)} />}
    </>
  )
}
