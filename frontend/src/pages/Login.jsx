import { useState } from 'react'
import { api } from '../api.js'
import { Alert } from '../ui.jsx'

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
    <main className="center-screen">
      <form className="auth" onSubmit={submit} aria-labelledby="login-title">
        <span className="brand-mark" aria-hidden="true">S</span>
        <div className="stack" style={{ gap: 6 }}>
          <h1 id="login-title">Snack-Drop</h1>
          <p className="secondary small">Procesa archivos en las computadoras de tu red, sin escritorio remoto.</p>
        </div>
        <label className="field">
          Usuario
          <input autoFocus autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="field">
          Contraseña
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <Alert tone="error">{error}</Alert>}
        <button className="btn primary large block" disabled={busy || !username || !password}>
          {busy ? 'Entrando…' : 'Iniciar sesión'}
        </button>
        <p className="caption">Las cuentas las crea un administrador.</p>
      </form>
    </main>
  )
}
