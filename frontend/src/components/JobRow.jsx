import { useState } from 'react'
import { Download, Server, SquareTerminal, Trash2, X } from 'lucide-react'
import { api } from '../api.js'
import { describeParams, formatBytes, formatDate, formatDuration, isActive } from '../format.js'
import { Alert, JOB_STATUS, OpIcon, Progress, StatusPill } from '../ui.jsx'

export default function JobRow({ job, me, onLogs, catalog = [] }) {
  const [error, setError] = useState('')
  const active = isActive(job)
  const op = catalog.find((c) => c.id === job.operation)
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
    `${job.inputs.length} archivo${job.inputs.length === 1 ? '' : 's'} · ${formatBytes(job.input_size)}`,
    describeParams(job.operation, job.params, op),
  ]
  if (job.status === 'done' && job.output_size) meta.push(`resultado ${formatBytes(job.output_size)}`)
  if (job.started_at) meta.push(formatDuration(job.started_at, job.finished_at))

  return (
    <div className="job">
      <OpIcon operation={job.operation} size={40} glyph={20} />
      <div className="body">
        <div className="title-line">
          <b className="truncate" title={job.title}>{job.title}</b>
          <StatusPill status={job.status} />
          {node && (
            <span className="caption row hide-compact" style={{ gap: 4 }}>
              <Server size={12} aria-hidden="true" /> {node}
            </span>
          )}
        </div>
        <div className="meta truncate">{meta.join(' · ')}</div>
        {active && job.status !== 'queued' && (
          <div className="progress-line">
            <Progress value={job.progress} indeterminate={job.status === 'assigned'} />
            <span className="pct">{job.status === 'assigned' ? '' : `${Math.round(job.progress)}%`}</span>
          </div>
        )}
        <div className="caption truncate">
          {active ? job.message || JOB_STATUS[job.status]?.label : formatDate(job.finished_at || job.created_at)}
          {!active && job.message && job.status === 'done' ? ` · ${job.message}` : ''}
          {job.owner_id !== me.id ? ` · de ${job.owner}` : ''}
        </div>
        {job.error && <Alert tone="error">{job.error}</Alert>}
        {job.failures?.length > 0 && (
          <details className="failures">
            <summary>
              {job.failures.length === 1 ? '1 archivo no se pudo procesar' : `${job.failures.length} archivos no se pudieron procesar`} — ver detalle
            </summary>
            <ul>
              {job.failures.map((f, i) => (
                <li key={i}>
                  <b>{f.filename}</b>: {f.error.startsWith(`${f.filename}: `) ? f.error.slice(f.filename.length + 2) : f.error}
                </li>
              ))}
            </ul>
          </details>
        )}
        {!active && job.expires_at && (
          <div className="caption">
            {job.outputs.length ? 'Disponible hasta' : 'Se elimina el'} {formatDate(job.expires_at)}
          </div>
        )}
        {error && <Alert tone="error">{error}</Alert>}
      </div>
      <div className="actions">
        {job.status === 'done' && isOwner && (
          <a className="btn tinted" href={`/api/jobs/${job.id}/download`} aria-label={`Descargar resultados de ${job.title}`}>
            <Download size={15} aria-hidden="true" />
            <span className="hide-compact">Descargar</span>
          </a>
        )}
        <button className="icon-btn" title="Ver registro" aria-label="Ver registro" onClick={() => onLogs(job)}>
          <SquareTerminal size={17} />
        </button>
        {active && (
          <button className="icon-btn danger" title="Cancelar" aria-label="Cancelar trabajo" onClick={() => act(() => api.post(`/api/jobs/${job.id}/cancel`))}>
            <X size={17} />
          </button>
        )}
        {!active && job.owner_id === me.id && (
          <button className="icon-btn danger" title="Eliminar" aria-label="Eliminar trabajo" onClick={() => act(() => api.del(`/api/jobs/${job.id}`))}>
            <Trash2 size={16} />
          </button>
        )}
      </div>
    </div>
  )
}
