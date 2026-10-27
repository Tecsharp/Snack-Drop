import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import Modal from './Modal.jsx'

export default function LogModal({ job, liveEvents, onClose }) {
  const [initial, setInitial] = useState(null)
  const [error, setError] = useState('')
  const [since] = useState(() => liveEvents.length)
  const bottom = useRef(null)

  useEffect(() => {
    api.get(`/api/jobs/${job.id}/logs`).then(setInitial).catch((e) => setError(e.message))
  }, [job.id])

  const lines = useMemo(() => {
    const live = liveEvents.slice(since).filter((e) => e.job_id === job.id)
    return [...(initial || []), ...live]
  }, [initial, liveEvents, since, job.id])

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [lines.length])

  return (
    <Modal title={`Logs · ${job.title}`} onClose={onClose} wide>
      {error && <div className="alert error">{error}</div>}
      <pre className="terminal">
        {initial === null && !error ? 'Cargando…' : null}
        {lines.map((l, i) => (
          <div key={i}>
            <span className="muted">{new Date(l.ts).toLocaleTimeString()} </span>
            {l.line}
          </div>
        ))}
        <span ref={bottom} />
      </pre>
    </Modal>
  )
}
