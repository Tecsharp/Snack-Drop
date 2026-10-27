import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { api } from '../api.js'

export default function ChangePassword({ me, onDone, onLogout, forced = false }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setOk('')
    if (next !== confirm) {
      setError('Las contraseñas no coinciden')
      return
    }
    setBusy(true)
    try {
      const user = await api.post('/api/auth/change-password', { current_password: current, new_password: next })
      setCurrent('')
      setNext('')
      setConfirm('')
      setOk('Contraseña actualizada. Las demás sesiones se cerraron.')
      onDone(user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const form = (
    <form className="card auth-card" onSubmit={submit}>
      <h2>
        <KeyRound size={20} /> {forced ? 'Crea tu contraseña' : 'Cambiar contraseña'}
      </h2>
      {forced && <p className="muted">Hola {me.username}, debes reemplazar la contraseña temporal antes de continuar.</p>}
      <label>
        Contraseña actual
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label>
        Nueva contraseña
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
      </label>
      <label>
        Confirmar nueva contraseña
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      <p className="muted small">Mínimo 10 caracteres con tres de: minúsculas, mayúsculas, números y símbolos.</p>
      {error && <div className="alert error">{error}</div>}
      {ok && <div className="alert success">{ok}</div>}
      <button className="btn primary" disabled={busy}>
        {busy ? 'Guardando…' : 'Guardar'}
      </button>
      {forced && (
        <button type="button" className="btn ghost" onClick={onLogout}>
          Cerrar sesión
        </button>
      )}
    </form>
  )

  return forced ? <div className="center-screen">{form}</div> : <div className="page-narrow">{form}</div>
}
