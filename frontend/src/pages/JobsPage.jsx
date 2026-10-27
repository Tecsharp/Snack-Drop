import { useMemo, useState } from 'react'
import { Inbox, Search } from 'lucide-react'
import JobRow from '../components/JobRow.jsx'
import LogModal from '../components/LogModal.jsx'
import Toolbar from '../components/Toolbar.jsx'
import { isActive } from '../format.js'
import { Empty, Segmented } from '../ui.jsx'

const FILTERS = [
  { value: 'all', label: 'Todos' },
  { value: 'active', label: 'En curso' },
  { value: 'done', label: 'Listos' },
  { value: 'problems', label: 'Con problemas' },
]

function dayLabel(iso) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(Date.now() - 86_400_000)
  if (d.toDateString() === today.toDateString()) return 'Hoy'
  if (d.toDateString() === yesterday.toDateString()) return 'Ayer'
  return d.toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric', month: 'long' })
}

export default function JobsPage({ me, jobs, catalog, logEvents }) {
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [logJob, setLogJob] = useState(null)

  const counts = {
    all: jobs.length,
    active: jobs.filter(isActive).length,
    done: jobs.filter((j) => j.status === 'done').length,
    problems: jobs.filter((j) => j.status === 'failed' || j.failures?.length).length,
  }

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const title = (id) => catalog.find((c) => c.id === id)?.title || id
    const list = jobs.filter((j) => {
      if (filter === 'active' && !isActive(j)) return false
      if (filter === 'done' && j.status !== 'done') return false
      if (filter === 'problems' && !(j.status === 'failed' || j.failures?.length)) return false
      if (!q) return true
      return `${j.title} ${title(j.operation)} ${j.assigned_node_name || ''} ${j.owner}`.toLowerCase().includes(q)
    })
    const map = new Map()
    list.forEach((j) => {
      const key = dayLabel(j.created_at)
      map.set(key, [...(map.get(key) || []), j])
    })
    return [...map.entries()]
  }, [jobs, filter, query, catalog])

  return (
    <>
      <Toolbar title="Trabajos" subtitle={`${counts.all} en total · ${counts.active} en curso`} />
      <div className="page">
        <div className="filters">
          <Segmented
            label="Filtrar trabajos"
            value={filter}
            onChange={setFilter}
            options={FILTERS.map((f) => ({ value: f.value, label: `${f.label}${counts[f.value] ? ` ${counts[f.value]}` : ''}` }))}
          />
          <div className="search grow" style={{ maxWidth: 340, minWidth: 200 }}>
            <Search size={15} aria-hidden="true" />
            <input type="search" placeholder="Buscar archivo, operación o computadora" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar trabajos" />
          </div>
        </div>
        {groups.length === 0 && (
          <div className="group">
            <Empty icon={Inbox} title={query ? 'Sin resultados' : 'No hay trabajos aquí'}>
              {query ? `Nada coincide con «${query}».` : 'Cambia el filtro o envía un trabajo desde Inicio.'}
            </Empty>
          </div>
        )}
        {groups.map(([day, list]) => (
          <section key={day} className="section">
            <div className="section-head">
              <h2 style={{ textTransform: 'capitalize' }}>{day}</h2>
              <span className="caption">{list.length}</span>
            </div>
            <div className="group">
              {list.map((j) => (
                <JobRow key={j.id} job={j} me={me} onLogs={setLogJob} catalog={catalog} />
              ))}
            </div>
          </section>
        ))}
      </div>
      {logJob && <LogModal job={logJob} liveEvents={logEvents} onClose={() => setLogJob(null)} />}
    </>
  )
}
