import { useMemo, useRef, useState } from 'react'
import { Sparkles, Upload, Send, X } from 'lucide-react'
import { api } from '../api.js'
import { formatBytes } from '../format.js'
import SchemaForm from './SchemaForm.jsx'

const GROUPS = [
  { exts: ['.heic', '.heif'], op: 'image.heic' },
  { exts: ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.avif'], op: 'image.convert' },
  { exts: ['.pdf'], op: 'pdf.compress' },
  { exts: ['.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.mpg', '.mpeg', '.wmv', '.flv', '.ts', '.3gp', '.mts'], op: 'video.compress' },
  { exts: ['.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.opus', '.wma', '.aiff', '.aif'], op: 'audio.convert' },
  { exts: ['.doc', '.docx', '.odt', '.rtf', '.xls', '.xlsx', '.ods', '.ppt', '.pptx', '.odp'], op: 'doc.to_pdf' },
  { exts: ['.zip', '.7z', '.tar', '.gz', '.tgz', '.bz2', '.xz'], op: 'archive.extract' },
]

const extOf = (name) => (name.lastIndexOf('.') >= 0 ? name.slice(name.lastIndexOf('.')).toLowerCase() : '')

export function accepts(op, name) {
  if (!op) return false
  const exts = op.extensions || []
  if (exts.includes('*')) return true
  const lower = name.toLowerCase()
  return exts.some((e) => lower.endsWith(e))
}

/** Operación sugerida para un conjunto de archivos (si todos son del mismo tipo). */
export function suggestOperation(names) {
  const ops = new Set(names.map((n) => GROUPS.find((g) => g.exts.includes(extOf(n)))?.op || null))
  return ops.size === 1 ? [...ops][0] : null
}

export default function NewJob({ catalog, nodes }) {
  const [files, setFiles] = useState([])
  const [operation, setOperation] = useState('image.convert')
  const [paramsByOp, setParamsByOp] = useState({})
  const [nodeId, setNodeId] = useState('auto')
  const [instruction, setInstruction] = useState('')
  const [planInfo, setPlanInfo] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [drag, setDrag] = useState(false)
  const [upload, setUpload] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  const op = catalog.find((c) => c.id === operation)
  const params = { ...(op?.defaults || {}), ...(paramsByOp[operation] || {}) }
  const setParams = (patch) => setParamsByOp((p) => ({ ...p, [operation]: { ...params, ...patch } }))

  const valid = useMemo(() => files.filter((f) => accepts(op, f.name)), [files, op])
  const invalid = files.length - valid.length
  const totalSize = valid.reduce((s, f) => s + f.size, 0)

  const eligibleNodes = nodes.filter((n) => !n.capabilities.length || n.capabilities.includes(operation))
  const runnable = (id) => nodes.some((n) => n.online && n.capabilities.includes(id))
  const categories = useMemo(() => {
    const map = new Map()
    catalog.forEach((c) => map.set(c.category, [...(map.get(c.category) || []), c]))
    return [...map.entries()]
  }, [catalog])
  const tooFew = op && valid.length > 0 && valid.length < op.min_files

  const addFiles = (list) => {
    const incoming = Array.from(list || [])
    if (!incoming.length) return
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`))
      return [...prev, ...incoming.filter((f) => !seen.has(`${f.name}:${f.size}`))]
    })
    // Elegir la operación según el tipo de archivo, si la actual no los acepta.
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
      setError('Agrega archivos compatibles con la operación seleccionada.')
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
      setFiles([])
      setPlanInfo(null)
      setInstruction('')
    } catch (err) {
      setError(err.message)
    } finally {
      setUpload(null)
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div className="panel-title">
          <Upload size={18} /> Nuevo trabajo
        </div>
      </div>
      <div className="newjob">
        <div
          className={`dropzone ${drag ? 'drag' : ''}`}
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
          {files.length === 0 ? (
            <>
              <Upload size={28} className="accent" />
              <div>Arrastra imágenes, PDFs, videos, audios o documentos aquí, o haz clic para elegir</div>
              <div className="muted small">Puedes soltar cientos de archivos: se procesan como un lote.</div>
            </>
          ) : (
            <>
              <div className="big-number">{valid.length}</div>
              <div>
                archivo{valid.length === 1 ? '' : 's'} listo{valid.length === 1 ? '' : 's'} · {formatBytes(totalSize)}
              </div>
              {invalid > 0 && <div className="warn small">{invalid} no compatible(s) con esta operación; se omitirán</div>}
              <button
                className="btn ghost small"
                onClick={(e) => {
                  e.stopPropagation()
                  setFiles([])
                }}
              >
                <X size={14} /> Quitar todos
              </button>
            </>
          )}
        </div>

        <div className="newjob-form">
          <div className="assistant">
            <Sparkles size={16} className="accent" />
            <input
              placeholder="Describe lo que quieres: «convierte a WebP calidad 75, máx 1920px, en SHRIMPDADDY»"
              value={instruction}
              maxLength={1000}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && askAssistant()}
            />
            <button className="btn outline" onClick={askAssistant} disabled={planning || !instruction.trim()}>
              {planning ? 'Pensando…' : 'Interpretar'}
            </button>
          </div>
          {planInfo && (
            <div className={`alert ${planInfo.operation ? 'info' : 'warn'} small`}>
              {planInfo.explanation || (planInfo.operation ? 'Listo.' : 'No se encontró una operación.')}{' '}
              <span className="muted">({planInfo.source === 'deepseek' ? 'DeepSeek' : 'intérprete local'})</span>
              {planInfo.warning && <div>{planInfo.warning}</div>}
            </div>
          )}

          <div className="param-grid">
            <label>
              Operación
              <select value={operation} onChange={(e) => setOperation(e.target.value)}>
                {categories.map(([category, ops]) => (
                  <optgroup key={category} label={category}>
                    {ops.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title}
                        {runnable(c.id) ? '' : ' — sin nodo compatible'}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label>
              Ejecutar en
              <select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
                <option value="auto">Automático (primer nodo libre)</option>
                {eligibleNodes.map((n) => (
                  <option key={n.id} value={String(n.id)}>
                    {n.name} — {n.online ? (n.is_paused ? 'pausado' : 'en línea') : 'desconectado'}
                    {n.can_manage ? '' : ` (de ${n.owner})`}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {op && (
            <p className="muted small op-desc">
              {op.description}
              {op.mode === 'batch' ? ' Procesa todos los archivos juntos.' : ''}
              {op.requires ? ` ${op.requires}.` : ''}
            </p>
          )}
          {op && !runnable(op.id) && (
            <div className="alert warn small">
              Ningún nodo conectado puede ejecutar esta operación ahora. El trabajo quedará en cola hasta que se conecte uno
              compatible.
            </div>
          )}
          {op && <SchemaForm schema={op.schema} values={params} onChange={setParams} />}
          {['image.convert', 'image.avif', 'image.heic'].includes(operation) && !params.lossless && params.quality > 90 && (
            <div className="alert warn small">
              Calidad mayor a 90 casi siempre produce archivos más pesados que un JPEG de cámara. Para fotos, 75–85 se ve igual y pesa
              mucho menos.
            </div>
          )}
          {tooFew && <div className="alert warn small">Esta operación necesita al menos {op.min_files} archivos.</div>}

          {error && <div className="alert error small">{error}</div>}
          {upload !== null && (
            <div className="progress">
              <div className="progress-fill" style={{ width: `${upload * 100}%` }} />
              <span className="progress-label">Subiendo {Math.round(upload * 100)}%</span>
            </div>
          )}
          <button className="btn primary" onClick={submit} disabled={upload !== null || !valid.length || tooFew}>
            <Send size={16} /> Enviar {valid.length ? `${valid.length} archivo${valid.length === 1 ? '' : 's'}` : ''}
          </button>
        </div>
      </div>
    </section>
  )
}
