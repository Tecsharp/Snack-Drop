import { useCallback, useEffect, useState } from 'react'
import { KeyRound, Trash2, UserPlus } from 'lucide-react'
import { api } from '../api.js'
import { formatDate } from '../format.js'
import Modal from '../components/Modal.jsx'

export default function UsersPage({ me }) {
  const [users, setUsers] = useState([])
  const [username, setUsername] = useState('')
  const [role, setRole] = useState('user')
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

  const create = (e) => {
    e.preventDefault()
    run(async () => {
      const res = await api.post('/api/users', { username, role })
      setSecret({ username: res.user.username, password: res.temporary_password })
      setUsername('')
      setRole('user')
    })
  }

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div className="panel-title">
            <UserPlus size={18} /> Crear usuario
          </div>
        </div>
        <form className="row gap wrap pad" onSubmit={create}>
          <input placeholder="usuario" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} maxLength={32} />
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="user">Usuario</option>
            <option value="admin">Administrador</option>
          </select>
          <button className="btn primary">Crear con contraseña temporal</button>
        </form>
        {error && <div className="alert error small">{error}</div>}
      </section>
      <section className="panel">
        <div className="panel-head">
          <div className="panel-title">Usuarios ({users.length})</div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Usuario</th>
                <th>Rol</th>
                <th>Estado</th>
                <th>Último acceso</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.username} {u.id === me.id && <span className="pill">tú</span>}
                  </td>
                  <td>
                    <select
                      value={u.role}
                      disabled={u.id === me.id}
                      onChange={(e) => run(() => api.patch(`/api/users/${u.id}`, { role: e.target.value }))}
                    >
                      <option value="user">Usuario</option>
                      <option value="admin">Administrador</option>
                    </select>
                  </td>
                  <td>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={u.is_active}
                        disabled={u.id === me.id}
                        onChange={(e) => run(() => api.patch(`/api/users/${u.id}`, { is_active: e.target.checked }))}
                      />{' '}
                      {u.is_active ? 'Activo' : 'Desactivado'}
                    </label>
                    {u.must_change_password && <div className="muted small">Debe cambiar contraseña</div>}
                  </td>
                  <td className="small muted">{formatDate(u.last_login_at)}</td>
                  <td className="row gap">
                    <button
                      className="btn outline"
                      onClick={() =>
                        run(async () => {
                          const res = await api.post(`/api/users/${u.id}/reset-password`)
                          setSecret({ username: u.username, password: res.temporary_password })
                        })
                      }
                    >
                      <KeyRound size={14} /> Restablecer
                    </button>
                    {u.id !== me.id && (
                      <button
                        className="icon-btn danger"
                        title="Eliminar"
                        onClick={() => window.confirm(`¿Eliminar a ${u.username} y sus trabajos?`) && run(() => api.del(`/api/users/${u.id}`))}
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {secret && (
        <Modal title="Contraseña temporal" onClose={() => setSecret(null)}>
          <p>
            Entrega esta contraseña a <b>{secret.username}</b> por un canal seguro. Deberá cambiarla al iniciar sesión y no se
            volverá a mostrar.
          </p>
          <div className="copy-field">
            <code>{secret.password}</code>
          </div>
        </Modal>
      )}
    </>
  )
}
