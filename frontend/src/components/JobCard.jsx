import { useState } from 'react'
import { Download, FileImage, FileText, Server, SquareTerminal, Trash2, X } from 'lucide-react'
import { api } from '../api.js'
import { describeParams, formatBytes, formatDate, formatDuration, isActive, statusLabel } from '../format.js'

export default function JobCard({ job, me, onLogs }) {
  const [error, setError] = useState('')
  const active = isActive(job)
  const Icon = job.operation === 'pdf.compress' ? FileText : FileImage
  const node = job.assigned_node_name || job.target_node_name
  const isOwner = me.role === 'admin' || job.owner_id === me.id

  const act = async (fn) => {
    setError('')
    try {
      await fn()
    } catch (err) {
      setError(err.message)
    }
  }

  const meta = [
    `${job.inputs.length} archivo${job.inputs.length === 1 ? '' : 's'}`,
    formatBytes(job.input_size),
    describeParams(job.operation, job.params),
  ]
  if (job.started_at) meta.push(formatDuration(job.started_at, job.finished_at))
  if (job.status === 'done' && job.output_size) meta.push(`→ ${formatBytes(job.output_size)}`)

  return (
    <div className={`job-card status-${job.status}`}>
      <div className="job-head">
        <div className="job-title">
          <Icon size={16} className="accent" />
          <span className="truncate" title={job.title}>{job.title}</span>
          <span className={`badge badge-${job.status}`}>{statusLabel(job.status)}</span>
          {node && (
            <span className="badge badge-node">
              <Server size={12} /> {node}
            </span>
          )}
          {job.owner_id !== me.id && <span className="muted small">de {job.owner}</span>}
        </div>
        <div className="job-actions">
          {job.status === 'done' && isOwner && (
            <a className="icon-btn ok" title="Descargar resultados" href={`/api/jobs/${job.id}/download`}>
              <Download size={16} />
            </a>
          )}
          {active && (
            <button className="icon-btn danger" title="Cancelar" onClick={() => act(() => api.post(`/api/jobs/${job.id}/cancel`))}>
              <X size={16} />
            </button>
          )}
          {!active && job.owner_id === me.id && (
            <button className="icon-btn danger" title="Eliminar" onClick={() => act(() => api.del(`/api/jobs/${job.id}`))}>
              <Trash2 size={16} />
            </button>
          )}
          <button className="icon-btn accent" title="Ver logs" onClick={() => onLogs(job)}>
            <SquareTerminal size={16} />
          </button>
        </div>
      </div>
      <div className="muted small">{meta.join(' • ')}</div>
      {(active || job.status === 'done') && (
        <div className="progress">
          <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} />
          <span className="progress-label">{Math.round(job.progress)}%</span>
        </div>
      )}
      <div className="row space small">
        <span className="muted">{formatDate(job.created_at)}</span>
        <span className="muted truncate">{job.message}</span>
      </div>
      {job.error && <div className="alert error small">{job.error}</div>}
      {job.failures?.length > 0 && (
        <details className="failures">
          <summary className="warn small">
            {job.failures.length === 1
              ? '1 archivo no se pudo procesar'
              : `${job.failures.length} archivos no se pudieron procesar`}{' '}
            — ver detalle
          </summary>
          <ul>
            {job.failures.map((f, i) => (
              <li key={i} className="small">
                <b>{f.filename}</b>:{' '}
                <span className="muted">{f.error.startsWith(`${f.filename}: `) ? f.error.slice(f.filename.length + 2) : f.error}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {!active && (job.expires_at || job.inputs_deleted) && (
        <div className="muted small">
          {job.inputs_deleted ? 'Originales borrados del servidor. ' : ''}
          {job.expires_at ? `${job.outputs.length ? 'Resultados disponibles' : 'Se elimina'} hasta ${formatDate(job.expires_at)}.` : ''}
        </div>
      )}
      {error && <div className="alert error small">{error}</div>}
    </div>
  )
}
