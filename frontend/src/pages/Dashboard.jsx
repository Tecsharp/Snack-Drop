import { useEffect, useState } from 'react'
import { Activity, CheckCircle2, Clock, Cpu, Inbox, Laptop, Monitor, Pause, Play, Plus } from 'lucide-react'
import { api } from '../api.js'
import JobRow from '../components/JobRow.jsx'
import LogModal from '../components/LogModal.jsx'
import NewJob from '../components/NewJob.jsx'
import Toolbar from '../components/Toolbar.jsx'
import { isActive } from '../format.js'
import { Empty, nodeState, Progress } from '../ui.jsx'

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches'
}

function NodeTile({ node }) {
  const [busy, setBusy] = useState(false)
  const s = nodeState(node)
  const working = Boolean(node.current_job)
  const Glyph = node.kind === 'master' ? Monitor : node.os === 'macOS' ? Laptop : Cpu
  const toggle = async () => {
    setBusy(true)
    try {
      await api.patch(`/api/nodes/${node.id}`, { is_paused: !node.is_paused })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className={`card node-tile ${working ? 'busy' : ''}`}>
      <div className="row">
        <span className="node-glyph" aria-hidden="true">
          <Glyph size={18} />
        </span>
        <div className="grow">
          <div className="row" style={{ gap: 6 }}>
            <b className="truncate">{node.name}</b>
            {node.gpu && <span className="pill accent">GPU</span>}
          </div>
          <div className="meta row" style={{ gap: 6 }}>
            <span className={`dot ${s.dot}`} aria-hidden="true" />
            {s.label}
          </div>
        </div>
        {node.can_manage && (
          <button
            className="icon-btn"
            onClick={toggle}
            disabled={busy}
            aria-label={node.is_paused ? `Reanudar ${node.name}` : `Pausar ${node.name}`}
            title={node.is_paused ? 'Reanudar' : 'Pausar'}
          >
            {node.is_paused ? <Play size={16} /> : <Pause size={16} />}
          </button>
        )}
      </div>
      {working ? (
        <div className="stack" style={{ gap: 6 }}>
          <span className="caption truncate">{node.current_job.title}</span>
          <Progress value={node.current_job.progress} />
        </div>
      ) : (
        <div className="meta truncate">
          {[node.os, node.accelerator].filter(Boolean).join(' · ') || 'Esperando primera conexión'} · {node.jobs_done} hechos
        </div>
      )}
    </div>
  )
}

export default function Dashboard({ me, nodes, jobs, catalog, logEvents, go }) {
  const [logJob, setLogJob] = useState(null)
  const [, tick] = useState(0)
  const active = jobs.filter(isActive).sort((a, b) => a.created_at.localeCompare(b.created_at))
  const running = active.filter((j) => j.status !== 'queued')
  const queued = active.length - running.length
  const today = new Date().toDateString()
  const doneToday = jobs.filter((j) => j.status === 'done' && j.finished_at && new Date(j.finished_at).toDateString() === today).length
  const online = nodes.filter((n) => n.online).length
  const recent = jobs.filter((j) => !isActive(j)).slice(0, 5)

  // Refresca las duraciones de los trabajos en curso.
  useEffect(() => {
    if (!active.length) return undefined
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [active.length])

  const stats = [
    { label: 'Procesando', value: running.length, icon: Activity },
    { label: 'En cola', value: queued, icon: Clock },
    { label: 'Listos hoy', value: doneToday, icon: CheckCircle2 },
    { label: 'Computadoras', value: `${online}/${nodes.length}`, icon: Monitor },
  ]

  return (
    <>
      <Toolbar title={`${greeting()}, ${me.username}`} subtitle="Suelta archivos, elige qué hacer y una computadora lo procesa por ti." />
      <div className="page">
        <div className="stats" role="list">
          {stats.map((s) => (
            <div key={s.label} className="card stat" role="listitem">
              <span className="value">{s.value}</span>
              <span className="label">
                <s.icon size={14} aria-hidden="true" /> {s.label}
              </span>
            </div>
          ))}
        </div>

        <NewJob catalog={catalog} nodes={nodes} />

        <section className="section" aria-labelledby="running-title">
          <div className="section-head">
            <h2 id="running-title">En curso</h2>
            {active.length > 0 && <span className="caption">{active.length} trabajo{active.length === 1 ? '' : 's'}</span>}
          </div>
          <div className="group">
            {active.length === 0 ? (
              <Empty icon={Inbox} title="Nada en proceso">Los trabajos que envíes aparecerán aquí con su progreso en vivo.</Empty>
            ) : (
              active.map((j) => <JobRow key={j.id} job={j} me={me} onLogs={setLogJob} catalog={catalog} />)
            )}
          </div>
        </section>

        <section className="section" aria-labelledby="nodes-title">
          <div className="section-head">
            <h2 id="nodes-title">Computadoras</h2>
            <button className="btn plain" style={{ marginLeft: 'auto' }} onClick={() => go('nodes')}>
              <Plus size={15} aria-hidden="true" /> Agregar
            </button>
          </div>
          {nodes.length === 0 ? (
            <div className="group">
              <Empty icon={Monitor} title="Aún no hay computadoras">Agrega una para empezar a repartir trabajo.</Empty>
            </div>
          ) : (
            <div className="nodes-strip">
              {nodes.map((n) => (
                <NodeTile key={n.id} node={n} />
              ))}
            </div>
          )}
        </section>

        {recent.length > 0 && (
          <section className="section" aria-labelledby="recent-title">
            <div className="section-head">
              <h2 id="recent-title">Recientes</h2>
              <button className="btn plain" style={{ marginLeft: 'auto' }} onClick={() => go('jobs')}>
                Ver todos
              </button>
            </div>
            <div className="group">
              {recent.map((j) => (
                <JobRow key={j.id} job={j} me={me} onLogs={setLogJob} catalog={catalog} />
              ))}
            </div>
          </section>
        )}
      </div>
      {logJob && <LogModal job={logJob} liveEvents={logEvents} onClose={() => setLogJob(null)} />}
    </>
  )
}
