import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, KeyRound, Trash2, UserPlus, Users } from 'lucide-react'
import { api } from '../api.js'
import Toolbar from '../components/Toolbar.jsx'
import { formatDate } from '../format.js'
import { Alert, Empty, initials, Segmented, Sheet, Toggle } from '../ui.jsx'

function SecretSheet({ secret, onClose }) {
  const [copied, setCopied] = useState(false)
  return (
    <Sheet title="Contraseña temporal" onClose={onClose} footer={<button className="btn primary" onClick={onClose}>Listo</button>}>
      <p className="small" style={{ margin: 0 }}>
        Entrega esta contraseña a <b>{secret.username}</b> por un canal seguro. Tendrá que cambiarla al iniciar sesión y no se volverá
        a mostrar.
      </p>
      <div className="copy-field">
        <code style={{ fontSize: 16 }}>{secret.password}</code>
        <button
          className="icon-btn"
          aria-label="Copiar contraseña"
          onClick={() => {
            navigator.clipboard?.writeText(secret.password)
            setCopied(true)
          }}
        >
          {copied ? <Check size={15} /> : <Copy size={15} />}
        </button>
      </div>
    </Sheet>
  )
}

function CreateSheet({ onClose, onCreated }) {
  const [username, setUsername] = useState('')
  const [role, setRole] = useState('user')
  const [error, setError] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    setError('')
    try {
      onCreated(await api.post('/api/users', { username, role }))
    } catch (err) {
      setError(err.message)
    }
  }
  return (
    <Sheet
      title="Nuevo usuario"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" form="new-user" disabled={username.trim().length < 3}>Crear</button>
        </>
      }
    >
      <form id="new-user" className="stack" onSubmit={submit}>
        <label className="field">
          Nombre de usuario
          <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={32} placeholder="maria.lopez" autoComplete="off" />
          <span className="field-help">3 a 32 caracteres: letras, números, punto, guion o guion bajo.</span>
        </label>
        <div className="field">
          <span>Rol</span>
          <Segmented full label="Rol" value={role} onChange={setRole} options={[{ value: 'user', label: 'Usuario' }, { value: 'admin', label: 'Administrador' }]} />
        </div>
        <p className="caption" style={{ margin: 0 }}>Se generará una contraseña temporal segura que deberá cambiar al entrar.</p>
        {error && <Alert tone="error">{error}</Alert>}
      </form>
    </Sheet>
  )
}

export default function UsersPage({ me }) {
  const [users, setUsers] = useState([])
  const [creating, setCreating] = useState(false)
  const [secret, setSecret] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(() => api.get('/api/users').then(setUsers).catch((e) => setError(e.message)), [])
  useEffect(() => {
    load()
  }, [load])

  const run = async (fn) => {
    setError('')
    try {
      await fn()
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <Toolbar title="Usuarios" subtitle="Solo los administradores pueden crear cuentas. No hay registro público.">
        <button className="btn primary" onClick={() => setCreating(true)}>
          <UserPlus size={16} aria-hidden="true" /> Nuevo usuario
        </button>
      </Toolbar>
      <div className="page">
        {error && <Alert tone="error">{error}</Alert>}
        <div className="group">
          {users.length === 0 && <Empty icon={Users} title="Cargando usuarios…" />}
          {users.map((u) => (
            <div key={u.id} className="list-row" style={{ flexWrap: 'wrap' }}>
              <span className="avatar" aria-hidden="true">{initials(u.username)}</span>
              <div className="grow">
                <div className="row" style={{ gap: 6 }}>
                  <span className="title truncate">{u.username}</span>
                  {u.id === me.id && <span className="pill">tú</span>}
                  {u.must_change_password && <span className="pill orange">contraseña temporal</span>}
                  {!u.is_active && <span className="pill red">desactivado</span>}
                </div>
                <div className="caption">Último acceso: {formatDate(u.last_login_at)}</div>
              </div>
              <div className="row wrap" style={{ gap: 10 }}>
                <Segmented
                  label={`Rol de ${u.username}`}
                  value={u.role}
                  onChange={(role) => u.id !== me.id && run(() => api.patch(`/api/users/${u.id}`, { role }))}
                  options={[{ value: 'user', label: 'Usuario' }, { value: 'admin', label: 'Admin' }]}
                />
                {u.id !== me.id && (
                  <div style={{ width: 120 }}>
                    <Toggle label="Activo" checked={u.is_active} onChange={(v) => run(() => api.patch(`/api/users/${u.id}`, { is_active: v }))} />
                  </div>
                )}
                <button
                  className="icon-btn"
                  title="Restablecer contraseña"
                  aria-label={`Restablecer contraseña de ${u.username}`}
                  onClick={() =>
                    run(async () => {
                      const res = await api.post(`/api/users/${u.id}/reset-password`)
                      setSecret({ username: u.username, password: res.temporary_password })
                    })
                  }
                >
                  <KeyRound size={16} />
                </button>
                {u.id !== me.id && (
                  <button
                    className="icon-btn danger"
                    title="Eliminar"
                    aria-label={`Eliminar a ${u.username}`}
                    onClick={() => window.confirm(`¿Eliminar a ${u.username} y todos sus trabajos?`) && run(() => api.del(`/api/users/${u.id}`))}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <p className="footnote">Desactivar, cambiar el rol o restablecer la contraseña cierra las sesiones abiertas de esa persona.</p>
      </div>
      {creating && (
        <CreateSheet
          onClose={() => setCreating(false)}
          onCreated={async (res) => {
            setCreating(false)
            setSecret({ username: res.user.username, password: res.temporary_password })
            await load()
          }}
        />
      )}
      {secret && <SecretSheet secret={secret} onClose={() => setSecret(null)} />}
    </>
  )
}
