import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { formatTime } from '../format.js'
import { Alert, Sheet } from '../ui.jsx'

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

  const tone = (line) => (/ERROR|falló/i.test(line) ? 'err' : /OMITIDO/.test(line) ? 'skip' : '')

  return (
    <Sheet title={`Registro · ${job.title}`} onClose={onClose} wide>
      {error && <Alert tone="error">{error}</Alert>}
      <pre className="terminal" aria-live="polite">
        {initial === null && !error ? 'Cargando…' : null}
        {lines.map((l, i) => (
          <div key={i} className={tone(l.line)}>
            <span className="ts">{formatTime(l.ts, true)} </span>
            {l.line}
          </div>
        ))}
        <span ref={bottom} />
      </pre>
    </Sheet>
  )
}
