import React from 'react'
import { createRoot } from 'react-dom/client'
import './appearance.js'
import App from './App.jsx'
import './styles.css'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="center-screen">
          <div className="auth">
            <h1>Algo salió mal</h1>
            <p className="secondary small">{String(this.state.error.message || this.state.error)}</p>
            <button className="btn primary large block" onClick={() => window.location.reload()}>
              Recargar
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
