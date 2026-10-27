import { useEffect, useState } from 'react'
import { Cog, History } from 'lucide-react'
import ClusterPanel from '../components/ClusterPanel.jsx'
import JobCard from '../components/JobCard.jsx'
import LogModal from '../components/LogModal.jsx'
import NewJob from '../components/NewJob.jsx'
import { isActive } from '../format.js'

export default function Dashboard({ me, nodes, jobs, catalog, logEvents, onOpenNodes }) {
  const [logJob, setLogJob] = useState(null)
  const [, tick] = useState(0)
  const active = jobs.filter(isActive).sort((a, b) => a.created_at.localeCompare(b.created_at))
  const finished = jobs.filter((j) => !isActive(j))

  // Refresca duraciones de trabajos en curso.
  useEffect(() => {
    if (!active.length) return undefined
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [active.length])

  return (
    <>
      <ClusterPanel nodes={nodes} onOpenNodes={onOpenNodes} />
      <NewJob catalog={catalog} nodes={nodes} />
      <section className="panel highlight">
        <div className="panel-head">
          <div className="panel-title big">
            <Cog size={20} className={`accent ${active.some((j) => j.status === 'processing') ? 'spin' : ''}`} /> En proceso
            <span className="pill">{active.length}</span>
          </div>
        </div>
        <div className="job-list">
          {active.length === 0 && <div className="empty">Nada en proceso. Arrastra archivos arriba para empezar.</div>}
          {active.map((j) => (
            <JobCard key={j.id} job={j} me={me} onLogs={setLogJob} />
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <div className="panel-title">
            <History size={18} /> Historial
          </div>
        </div>
        <div className="job-list">
          {finished.length === 0 && <div className="empty">Aún no hay trabajos terminados.</div>}
          {finished.map((j) => (
            <JobCard key={j.id} job={j} me={me} onLogs={setLogJob} />
          ))}
        </div>
      </section>
      {logJob && <LogModal job={logJob} liveEvents={logEvents} onClose={() => setLogJob(null)} />}
    </>
  )
}
