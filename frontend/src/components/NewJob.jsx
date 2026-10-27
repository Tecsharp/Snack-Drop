import { useMemo, useRef, useState } from 'react'
import { Sparkles, Upload, Send, X } from 'lucide-react'
import { api } from '../api.js'
import { formatBytes } from '../format.js'

function ImageParams({ params, set }) {
  return (
    <div className="param-grid">
      <label>
        Formato
        <select value={params.format} onChange={(e) => set({ format: e.target.value })}>
          <option value="webp">WebP</option>
          <option value="jpeg">JPEG</option>
          <option value="png">PNG</option>
        </select>
      </label>
      <label>
        Calidad: {params.quality}
        <input
          type="range"
          min="1"
          max="100"
          value={params.quality}
          disabled={params.format === 'png' || params.lossless}
          onChange={(e) => set({ quality: Number(e.target.value) })}
        />
      </label>
      <label>
        Ancho máx. (px)
        <input
          type="number"
          min="16"
          max="16384"
          placeholder="Original"
          value={params.max_width ?? ''}
          onChange={(e) => set({ max_width: e.target.value ? Number(e.target.value) : null })}
        />
      </label>
      <label>
        Alto máx. (px)
        <input
          type="number"
          min="16"
          max="16384"
          placeholder="Original"
          value={params.max_height ?? ''}
          onChange={(e) => set({ max_height: e.target.value ? Number(e.target.value) : null })}
        />
      </label>
      {params.format === 'webp' && (
        <label className="check">
          <input type="checkbox" checked={params.lossless} onChange={(e) => set({ lossless: e.target.checked })} /> Sin pérdida
        </label>
      )}
      <label className="check">
        <input type="checkbox" checked={params.strip_metadata} onChange={(e) => set({ strip_metadata: e.target.checked })} />{' '}
        Quitar metadatos (EXIF/GPS)
      </label>
    </div>
  )
}

function PdfParams({ params, set }) {
  return (
    <div className="param-grid">
      <label>
        Nivel de compresión
        <select value={params.level} onChange={(e) => set({ level: e.target.value })}>
          <option value="low">Ligera (calidad de impresión)</option>
          <option value="medium">Media (lectura en pantalla)</option>
          <option value="high">Máxima (archivo más pequeño)</option>
        </select>
      </label>
      <label className="check">
        <input type="checkbox" checked={params.grayscale} onChange={(e) => set({ grayscale: e.target.checked })} /> Escala de grises
      </label>
    </div>
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
  const [drag, setDrag] = useState(false)
  const [upload, setUpload] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  const op = catalog.find((c) => c.id === operation)
  const params = { ...(op?.defaults || {}), ...(paramsByOp[operation] || {}) }
  const setParams = (patch) => setParamsByOp((p) => ({ ...p, [operation]: { ...params, ...patch } }))

  const accepted = useMemo(() => new Set(op?.extensions || []), [op])
  const extOf = (name) => (name.lastIndexOf('.') >= 0 ? name.slice(name.lastIndexOf('.')).toLowerCase() : '')
  const valid = files.filter((f) => accepted.has(extOf(f.name)))
  const invalid = files.length - valid.length
  const totalSize = valid.reduce((s, f) => s + f.size, 0)

  const eligibleNodes = nodes.filter((n) => !n.capabilities.length || n.capabilities.includes(operation))

  const addFiles = (list) => {
    const incoming = Array.from(list || [])
    if (!incoming.length) return
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`))
      return [...prev, ...incoming.filter((f) => !seen.has(`${f.name}:${f.size}`))]
    })
    // Elegir la operación según el tipo de archivo, si es obvia.
    const exts = new Set(incoming.map((f) => extOf(f.name)))
    if (exts.size === 1 && exts.has('.pdf')) setOperation('pdf.compress')
    else if (![...exts].includes('.pdf')) setOperation('image.convert')
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
              <div>Arrastra imágenes o PDFs aquí, o haz clic para elegir</div>
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
                {catalog.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
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

          {operation === 'image.convert' && <ImageParams params={params} set={setParams} />}
          {operation === 'pdf.compress' && <PdfParams params={params} set={setParams} />}

          {error && <div className="alert error small">{error}</div>}
          {upload !== null && (
            <div className="progress">
              <div className="progress-fill" style={{ width: `${upload * 100}%` }} />
              <span className="progress-label">Subiendo {Math.round(upload * 100)}%</span>
            </div>
          )}
          <button className="btn primary" onClick={submit} disabled={upload !== null || !valid.length}>
            <Send size={16} /> Enviar {valid.length ? `${valid.length} archivo${valid.length === 1 ? '' : 's'}` : ''}
          </button>
        </div>
      </div>
    </section>
  )
}
