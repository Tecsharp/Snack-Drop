import { useState } from 'react'
import { Lock } from 'lucide-react'
import { api } from '../api.js'

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await api.post('/api/auth/login', { username, password }))
    } catch (err) {
      setError(err.message)
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center-screen">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand big">
          <span className="brand-logo">S</span>
          <span>Snack-Drop</span>
        </div>
        <p className="muted">Procesa archivos en las computadoras de tu red, sin escritorio remoto.</p>
        <label>
          Usuario
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Contraseña
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="btn primary" disabled={busy}>
          <Lock size={16} /> {busy ? 'Entrando…' : 'Iniciar sesión'}
        </button>
        <p className="muted small">Las cuentas las crea un administrador.</p>
      </form>
    </div>
  )
}
