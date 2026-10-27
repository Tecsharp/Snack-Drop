import { useState } from 'react'
import { ChevronDown, ChevronUp, Network, Pause, Play, Settings } from 'lucide-react'
import { api } from '../api.js'
import { statusLabel } from '../format.js'

function NodeCard({ node, onSettings }) {
  const [busy, setBusy] = useState(false)
  const toggle = async () => {
    setBusy(true)
    try {
      await api.patch(`/api/nodes/${node.id}`, { is_paused: !node.is_paused })
    } finally {
      setBusy(false)
    }
  }
  const platform = [node.os, node.accelerator].filter(Boolean).join(' / ') || 'Sin datos aún'
  return (
    <div className={`node-card state-${node.state}`}>
      <div className="node-name">
        <span className="dot" /> {node.name}
      </div>
      <div className="muted small">
        {node.kind === 'master' ? 'master' : 'node'} • {platform}
      </div>
      <div className="small">
        {statusLabel(node.state)}
        {node.is_paused && node.state !== 'paused' ? ' (pausará al terminar)' : ''}
      </div>
      <div className="muted small">
        Trabajos: {node.jobs_done} hechos, {node.jobs_failed} fallidos
      </div>
      {!node.can_manage && <div className="muted small">Compartido por {node.owner}</div>}
      {node.can_manage && (
        <div className="node-actions">
          <button className={`btn outline ${node.is_paused ? 'resume' : 'pause'}`} onClick={toggle} disabled={busy}>
            {node.is_paused ? <Play size={14} /> : <Pause size={14} />} {node.is_paused ? 'Reanudar' : 'Pausar'}
          </button>
          <button className="icon-btn" title="Configurar nodo" onClick={onSettings}>
            <Settings size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

export default function ClusterPanel({ nodes, onOpenNodes }) {
  const [open, setOpen] = useState(true)
  const manageable = nodes.filter((n) => n.can_manage)
  const allPaused = manageable.length > 0 && manageable.every((n) => n.is_paused)

  const toggleAll = async () => {
    await Promise.all(manageable.map((n) => api.patch(`/api/nodes/${n.id}`, { is_paused: !allPaused })))
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <button className="panel-title as-button" onClick={() => setOpen(!open)}>
          <Network size={18} /> Clúster <span className="pill">{nodes.length} nodos</span>
        </button>
        <div className="row gap">
          {manageable.length > 0 && (
            <button className={`btn outline ${allPaused ? 'resume' : 'pause'}`} onClick={toggleAll}>
              {allPaused ? <Play size={14} /> : <Pause size={14} />} {allPaused ? 'Reanudar todos' : 'Pausar todos'}
            </button>
          )}
          <button className="icon-btn" onClick={() => setOpen(!open)} aria-label="Mostrar u ocultar">
            {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
        </div>
      </div>
      {open && (
        <div className="node-grid">
          {nodes.length === 0 && (
            <div className="empty">
              No tienes nodos disponibles. <button className="link" onClick={onOpenNodes}>Agrega uno</button>.
            </div>
          )}
          {nodes.map((n) => (
            <NodeCard key={n.id} node={n} onSettings={onOpenNodes} />
          ))}
        </div>
      )}
    </section>
  )
}
