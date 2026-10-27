import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { api } from '../api.js'
import { Alert } from '../ui.jsx'

const RULES = [
  { test: (p) => p.length >= 10, label: '10 caracteres o más' },
  {
    test: (p) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length >= 3,
    label: 'Tres de: minúsculas, mayúsculas, números, símbolos',
  },
]

export default function ChangePassword({ me, onDone, onLogout, forced = false }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)

  const mismatch = confirm.length > 0 && next !== confirm
  const strong = RULES.every((r) => r.test(next)) && !next.toLowerCase().includes(me.username.toLowerCase())

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
      setOk('Contraseña actualizada. Se cerraron tus otras sesiones.')
      onDone(user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const form = (
    <form className={forced ? 'auth' : 'card pad stack'} onSubmit={submit}>
      {forced && (
        <>
          <span className="brand-mark" aria-hidden="true">
            <KeyRound size={28} />
          </span>
          <h1>Crea tu contraseña</h1>
          <p className="secondary small">Hola {me.username}. Antes de continuar, reemplaza la contraseña temporal por una tuya.</p>
        </>
      )}
      <label className="field">
        Contraseña actual
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label className="field">
        Nueva contraseña
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required aria-describedby="pw-rules" />
      </label>
      <ul id="pw-rules" className="caption" style={{ margin: 0, paddingLeft: 18 }}>
        {RULES.map((r) => (
          <li key={r.label} style={{ color: next && r.test(next) ? 'var(--green)' : undefined }}>
            {r.label}
          </li>
        ))}
        <li style={{ color: next && !next.toLowerCase().includes(me.username.toLowerCase()) ? 'var(--green)' : undefined }}>
          Que no contenga tu nombre de usuario
        </li>
      </ul>
      <label className="field">
        Confirmar nueva contraseña
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required aria-invalid={mismatch} />
        {mismatch && <span className="field-help" style={{ color: 'var(--red)' }}>No coincide con la nueva contraseña</span>}
      </label>
      {error && <Alert tone="error">{error}</Alert>}
      {ok && <Alert tone="success">{ok}</Alert>}
      <button className={`btn primary ${forced ? 'large block' : ''}`} disabled={busy || !strong || mismatch || !current} style={forced ? undefined : { alignSelf: 'flex-start' }}>
        {busy ? 'Guardando…' : 'Guardar contraseña'}
      </button>
      {forced && (
        <button type="button" className="btn plain" onClick={onLogout}>
          Cerrar sesión
        </button>
      )}
    </form>
  )

  return forced ? <div className="center-screen">{form}</div> : form
}
