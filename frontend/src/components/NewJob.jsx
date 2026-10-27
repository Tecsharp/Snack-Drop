import { useMemo, useRef, useState } from 'react'
import { ChevronRight, Search, Send, Sparkles, Upload, X } from 'lucide-react'
import { api } from '../api.js'
import { formatBytes } from '../format.js'
import { Alert, OpIcon, Progress, Sheet, useToast } from '../ui.jsx'
import SchemaForm from './SchemaForm.jsx'

const GROUPS = [
  { exts: ['.heic', '.heif'], op: 'image.heic', kind: 'Fotos HEIC' },
  { exts: ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.avif'], op: 'image.convert', kind: 'Imágenes' },
  { exts: ['.pdf'], op: 'pdf.compress', kind: 'PDF' },
  { exts: ['.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.mpg', '.mpeg', '.wmv', '.flv', '.ts', '.3gp', '.mts'], op: 'video.compress', kind: 'Videos' },
  { exts: ['.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.opus', '.wma', '.aiff', '.aif'], op: 'audio.convert', kind: 'Audios' },
  { exts: ['.doc', '.docx', '.odt', '.rtf', '.xls', '.xlsx', '.ods', '.ppt', '.pptx', '.odp'], op: 'doc.to_pdf', kind: 'Documentos' },
  { exts: ['.zip', '.7z', '.tar', '.gz', '.tgz', '.bz2', '.xz'], op: 'archive.extract', kind: 'Comprimidos' },
]

const extOf = (name) => (name.lastIndexOf('.') >= 0 ? name.slice(name.lastIndexOf('.')).toLowerCase() : '')
const groupOf = (name) => GROUPS.find((g) => g.exts.includes(extOf(name)))

export function accepts(op, name) {
  if (!op) return false
  const exts = op.extensions || []
  if (exts.includes('*')) return true
  const lower = name.toLowerCase()
  return exts.some((e) => lower.endsWith(e))
}

/** Operación sugerida para un conjunto de archivos (si todos son del mismo tipo). */
export function suggestOperation(names) {
  const ops = new Set(names.map((n) => groupOf(n)?.op || null))
  return ops.size === 1 ? [...ops][0] : null
}

function OperationPicker({ catalog, current, files, runnable, onPick, onClose }) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const fits = (op) => !files.length || files.every((f) => accepts(op, f.name))
  const match = (op) => !q || `${op.title} ${op.description} ${op.category}`.toLowerCase().includes(q)
  const suggested = files.length ? catalog.filter((op) => fits(op) && match(op) && !op.extensions.includes('*')) : []
  const categories = useMemo(() => {
    const map = new Map()
    catalog.filter(match).forEach((c) => map.set(c.category, [...(map.get(c.category) || []), c]))
    return [...map.entries()]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, q])

  const tile = (op) => (
    <button key={op.id} type="button" className="op-tile" aria-pressed={op.id === current} onClick={() => onPick(op.id)}>
      <OpIcon operation={op.id} size={30} glyph={16} />
      <span className="grow">
        <span className="t" style={{ display: 'block' }}>{op.title}</span>
        <span className="d" style={{ display: 'block' }}>
          {!fits(op) ? 'No acepta tus archivos' : !runnable(op.id) ? 'Sin computadora compatible ahora' : op.description}
        </span>
      </span>
    </button>
  )

  return (
    <Sheet title="¿Qué quieres hacer?" onClose={onClose} wide>
      <div className="search">
        <Search size={15} aria-hidden="true" />
        <input type="search" placeholder="Buscar: comprimir, unir, subtítulos, marca de agua…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar operación" />
      </div>
      {suggested.length > 0 && (
        <>
          <div className="op-cat">Para tus archivos</div>
          <div className="op-grid">{suggested.slice(0, 8).map(tile)}</div>
        </>
      )}
      {categories.map(([category, ops]) => (
        <div key={category} className="stack" style={{ gap: 8 }}>
          <div className="op-cat">{category}</div>
          <div className="op-grid">{ops.map(tile)}</div>
        </div>
      ))}
      {categories.length === 0 && <p className="caption">No hay operaciones que coincidan con «{query}».</p>}
    </Sheet>
  )
}

export default function NewJob({ catalog, nodes }) {
  const [files, setFiles] = useState([])
  const [operation, setOperation] = useState('image.convert')
  const [paramsByOp, setParamsByOp] = useState({})
  const [nodeId, setNodeId] = useState('auto')
  const [instruction, setInstruction] = useState('')
  const [planInfo, setPlanInfo] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [picker, setPicker] = useState(false)
  const [drag, setDrag] = useState(false)
  const [upload, setUpload] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)
  const toast = useToast()

  const op = catalog.find((c) => c.id === operation)
  const params = { ...(op?.defaults || {}), ...(paramsByOp[operation] || {}) }
  const setParams = (patch) => setParamsByOp((p) => ({ ...p, [operation]: { ...params, ...patch } }))

  const valid = useMemo(() => files.filter((f) => accepts(op, f.name)), [files, op])
  const invalid = files.length - valid.length
  const totalSize = valid.reduce((s, f) => s + f.size, 0)
  const kinds = useMemo(() => {
    const counts = new Map()
    files.forEach((f) => {
      const k = groupOf(f.name)?.kind || 'Otros'
      counts.set(k, (counts.get(k) || 0) + 1)
    })
    return [...counts.entries()]
  }, [files])

  const eligibleNodes = nodes.filter((n) => !n.capabilities.length || n.capabilities.includes(operation))
  const runnable = (id) => nodes.some((n) => n.online && n.capabilities.includes(id))
  const tooFew = op && valid.length > 0 && valid.length < op.min_files
  const missingRequired = (op?.schema?.required || []).some((k) => !String(params[k] ?? '').trim())

  const addFiles = (list) => {
    const incoming = Array.from(list || [])
    if (!incoming.length) return
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`))
      return [...prev, ...incoming.filter((f) => !seen.has(`${f.name}:${f.size}`))]
    })
    const current = catalog.find((c) => c.id === operation)
    if (!incoming.every((f) => accepts(current, f.name))) {
      const suggested = suggestOperation(incoming.map((f) => f.name))
      if (suggested && catalog.some((c) => c.id === suggested)) setOperation(suggested)
    }
  }

  const askAssistant = async () => {
    if (!instruction.trim()) return
    setPlanning(true)
    setError('')
    setPlanInfo(null)
    try {
      const plan = await api.post('/api/assistant/plan', { instruction })
      setPlanInfo(plan)
      if (plan.operation) {
        setOperation(plan.operation)
        setParamsByOp((p) => ({ ...p, [plan.operation]: plan.params }))
        if (plan.node_id) setNodeId(String(plan.node_id))
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setPlanning(false)
    }
  }

  const submit = async () => {
    setError('')
    if (!valid.length) {
      setError('Agrega archivos compatibles con la operación elegida.')
      return
    }
    const fd = new FormData()
    fd.append('operation', operation)
    fd.append('params', JSON.stringify(params))
    fd.append('node_id', nodeId)
    valid.forEach((f) => fd.append('files', f, f.name))
    setUpload(0)
    try {
      await api.upload('/api/jobs', fd, setUpload)
      toast({ tone: 'success', title: 'Trabajo enviado', body: `${op.title} · ${valid.length} archivo${valid.length === 1 ? '' : 's'}` })
      setFiles([])
      setPlanInfo(null)
      setInstruction('')
    } catch (err) {
      setError(err.message)
    } finally {
      setUpload(null)
    }
  }

  const step = (n, title, done, children) => (
    <div className={`step ${done ? 'done' : ''}`}>
      <div className="step-title">
        <span className="step-num" aria-hidden="true">{n}</span>
        {title}
      </div>
      {children}
    </div>
  )

  return (
    <section className="section" aria-labelledby="new-job-title">
      <div className="section-head">
        <h2 id="new-job-title">Nuevo trabajo</h2>
      </div>
      <div className="card composer">
        <div
          className={`drop ${drag ? 'drag' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDrag(true)
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDrag(false)
            addFiles(e.dataTransfer.files)
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          aria-label="Agregar archivos"
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              addFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <span className="drop-icon" aria-hidden="true">
            <Upload size={26} />
          </span>
          {files.length === 0 ? (
            <>
              <b>Suelta tus archivos aquí</b>
              <span className="small">o haz clic para elegirlos · fotos, PDF, video, audio, documentos</span>
            </>
          ) : (
            <div className="file-summary">
              <b className="tnum">
                {files.length} archivo{files.length === 1 ? '' : 's'} · {formatBytes(files.reduce((s, f) => s + f.size, 0))}
              </b>
              <div className="file-kinds">
                {kinds.map(([k, n]) => (
                  <span key={k} className="pill">
                    {n} {k}
                  </span>
                ))}
              </div>
              <span className="caption truncate">{files.slice(0, 3).map((f) => f.name).join(', ')}{files.length > 3 ? '…' : ''}</span>
              <div className="row" style={{ justifyContent: 'center', marginTop: 4 }}>
                <button className="btn plain" onClick={(e) => (e.stopPropagation(), inputRef.current?.click())}>
                  Agregar más
                </button>
                <button className="btn plain destructive" onClick={(e) => (e.stopPropagation(), setFiles([]))}>
                  <X size={14} /> Quitar todos
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="composer-form">
          <div className="assistant">
            <Sparkles size={16} aria-hidden="true" />
            <input
              placeholder="Pídelo con tus palabras: «comprime el video a 1080p en SHRIMPDADDY»"
              value={instruction}
              maxLength={1000}
              aria-label="Describe lo que quieres hacer"
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && askAssistant()}
            />
            <button className="btn tinted" onClick={askAssistant} disabled={planning || !instruction.trim()}>
              {planning ? 'Pensando…' : 'Interpretar'}
            </button>
          </div>
          {planInfo && (
            <Alert tone={planInfo.operation ? 'info' : 'warn'}>
              {planInfo.explanation || (planInfo.operation ? 'Listo.' : 'No encontré una operación para eso.')}{' '}
              <span className="caption">· {planInfo.source === 'deepseek' ? 'DeepSeek' : 'intérprete local'}</span>
              {planInfo.warning && <div>{planInfo.warning}</div>}
            </Alert>
          )}

          {step(1, 'Qué hacer', Boolean(op), (
            <>
              <button type="button" className="op-current" onClick={() => setPicker(true)} aria-haspopup="dialog">
                {op && <OpIcon operation={op.id} />}
                <span className="grow">
                  <span style={{ display: 'block', fontWeight: 600 }}>{op?.title || 'Elige una operación'}</span>
                  <span className="caption" style={{ display: 'block' }}>
                    {op?.description}
                    {op?.mode === 'batch' ? ' Procesa todos los archivos juntos.' : ''}
                  </span>
                </span>
                <span className="caption hide-compact">Cambiar</span>
                <ChevronRight size={16} aria-hidden="true" />
              </button>
              {op && !runnable(op.id) && (
                <Alert tone="warn">
                  Ninguna computadora conectada puede hacer esto ahora{op.requires ? ` (${op.requires.toLowerCase()})` : ''}. El
                  trabajo esperará en la cola.
                </Alert>
              )}
            </>
          ))}

          {op && step(2, 'Ajustes', true, (
            <>
              <SchemaForm key={op.id} schema={op.schema} values={params} onChange={setParams} />
              {['image.convert', 'image.avif', 'image.heic'].includes(operation) && !params.lossless && params.quality > 90 && (
                <Alert tone="warn">
                  Calidad mayor a 90 casi siempre pesa más que la foto original. Para fotos, 75–85 se ve igual.
                </Alert>
              )}
            </>
          ))}

          {step(3, 'Dónde', nodeId !== 'auto', (
            <select value={nodeId} onChange={(e) => setNodeId(e.target.value)} aria-label="Computadora que hará el trabajo">
              <option value="auto">Automático · la primera computadora libre</option>
              {eligibleNodes.map((n) => (
                <option key={n.id} value={String(n.id)}>
                  {n.name} · {n.online ? (n.is_paused ? 'en pausa' : 'disponible') : 'desconectada'}
                  {n.can_manage ? '' : ` · de ${n.owner}`}
                </option>
              ))}
            </select>
          ))}

          {invalid > 0 && files.length > 0 && (
            <Alert tone="warn">
              {invalid} archivo{invalid === 1 ? '' : 's'} no {invalid === 1 ? 'es compatible' : 'son compatibles'} con «{op?.title}» y se
              omitirá{invalid === 1 ? '' : 'n'}.
            </Alert>
          )}
          {tooFew && <Alert tone="warn">Esta operación necesita al menos {op.min_files} archivos.</Alert>}
          {error && <Alert tone="error">{error}</Alert>}
          {upload !== null && (
            <div className="stack" style={{ gap: 6 }}>
              <Progress value={upload * 100} />
              <span className="caption tnum">Subiendo {Math.round(upload * 100)}%</span>
            </div>
          )}
          <button className="btn primary large block" onClick={submit} disabled={upload !== null || !valid.length || tooFew || missingRequired}>
            <Send size={17} aria-hidden="true" />
            {valid.length ? `Enviar ${valid.length} archivo${valid.length === 1 ? '' : 's'} · ${formatBytes(totalSize)}` : 'Agrega archivos para empezar'}
          </button>
        </div>
      </div>

      {picker && (
        <OperationPicker
          catalog={catalog}
          current={operation}
          files={files}
          runnable={runnable}
          onClose={() => setPicker(false)}
          onPick={(id) => {
            setOperation(id)
            setPicker(false)
          }}
        />
      )}
    </section>
  )
}
