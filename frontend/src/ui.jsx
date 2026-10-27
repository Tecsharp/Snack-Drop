import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import {
  AlertTriangle,
  Archive,
  AudioWaveform,
  Captions,
  CheckCircle2,
  Combine,
  Crop,
  Eraser,
  EyeOff,
  FileDown,
  FileImage,
  FileText,
  Film,
  Fingerprint,
  Image,
  Images,
  Info,
  Lock,
  LockOpen,
  Maximize2,
  Music,
  PackageOpen,
  RotateCw,
  Scaling,
  ScanText,
  Shrink,
  Smartphone,
  Sparkles,
  Split,
  Stamp,
  TextCursorInput,
  Volume2,
  X,
  XCircle,
} from 'lucide-react'

/* ---------- Iconos y colores por operación ---------- */

const OP_ICONS = {
  'image.convert': Image,
  'image.heic': Smartphone,
  'image.avif': Sparkles,
  'image.watermark': Stamp,
  'image.crop': Crop,
  'image.strip': EyeOff,
  'image.rename': TextCursorInput,
  'image.remove_bg': Eraser,
  'image.upscale': Maximize2,
  'pdf.compress': FileDown,
  'pdf.merge': Combine,
  'pdf.split': Split,
  'pdf.from_images': Images,
  'pdf.to_images': FileImage,
  'pdf.rotate': RotateCw,
  'pdf.protect': Lock,
  'pdf.unlock': LockOpen,
  'pdf.ocr': ScanText,
  'pdf.watermark': Stamp,
  'video.compress': Shrink,
  'video.convert': Film,
  'video.resize': Scaling,
  'video.extract_audio': Music,
  'video.gif': Images,
  'video.thumbnails': Images,
  'audio.convert': Music,
  'audio.normalize': Volume2,
  'audio.transcribe': Captions,
  'doc.to_pdf': FileText,
  'archive.zip': Archive,
  'archive.extract': PackageOpen,
  'file.hash': Fingerprint,
}

export function opCategoryClass(operation = '') {
  const prefix = operation.split('.')[0]
  return { image: 'cat-image', pdf: 'cat-pdf', video: 'cat-video', audio: 'cat-audio', doc: 'cat-doc' }[prefix] || 'cat-archive'
}

export function OpIcon({ operation, size = 34, glyph = 18 }) {
  const Icon = OP_ICONS[operation] || AudioWaveform
  return (
    <span className={`op-icon ${opCategoryClass(operation)}`} style={{ width: size, height: size }} aria-hidden="true">
      <Icon size={glyph} strokeWidth={2} />
    </span>
  )
}

/* ---------- Estado de trabajos ---------- */

export const JOB_STATUS = {
  queued: { label: 'En cola', tone: '' },
  assigned: { label: 'Asignado', tone: 'blue' },
  downloading: { label: 'Recibiendo', tone: 'blue' },
  processing: { label: 'Procesando', tone: 'accent' },
  uploading: { label: 'Enviando resultados', tone: 'blue' },
  done: { label: 'Listo', tone: 'green' },
  failed: { label: 'Falló', tone: 'red' },
  cancelled: { label: 'Cancelado', tone: '' },
}

export function StatusPill({ status }) {
  const s = JOB_STATUS[status] || { label: status, tone: '' }
  return <span className={`pill ${s.tone}`}>{s.label}</span>
}

export const NODE_STATE = {
  online: { label: 'Disponible', dot: 'online' },
  offline: { label: 'Desconectado', dot: 'offline' },
  paused: { label: 'En pausa', dot: 'paused' },
  assigned: { label: 'Preparando', dot: 'busy' },
  downloading: { label: 'Recibiendo archivos', dot: 'busy' },
  processing: { label: 'Procesando', dot: 'busy' },
  uploading: { label: 'Enviando resultados', dot: 'busy' },
}

export const nodeState = (node) => NODE_STATE[node.state] || { label: node.state, dot: 'offline' }

/* ---------- Controles ---------- */

export function Toggle({ label, checked, onChange, help }) {
  const id = useId()
  return (
    <label className="switch-row" htmlFor={id} title={help || undefined}>
      <span className="grow">
        {label}
        {help && <span className="field-help" style={{ display: 'block' }}>{help}</span>}
      </span>
      <span className="switch">
        <input id={id} type="checkbox" role="switch" checked={Boolean(checked)} onChange={(e) => onChange(e.target.checked)} />
        <span className="track" />
        <span className="thumb" />
      </span>
    </label>
  )
}

export function Segmented({ options, value, onChange, label, full = false }) {
  return (
    <div className={`segmented ${full ? 'full' : ''}`} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Progress({ value, indeterminate = false, tone = '' }) {
  return (
    <div
      className={`progress ${indeterminate ? 'indeterminate' : ''} ${tone}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(value)}
    >
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="empty">
      {Icon && <Icon size={34} strokeWidth={1.5} aria-hidden="true" />}
      {title && <b>{title}</b>}
      {children && <div className="small">{children}</div>}
    </div>
  )
}

export function Alert({ tone = 'info', children }) {
  const Icon = { error: XCircle, warn: AlertTriangle, success: CheckCircle2, info: Info }[tone]
  return (
    <div className={`alert ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon size={16} aria-hidden="true" />
      <div className="grow">{children}</div>
    </div>
  )
}

/* ---------- Hoja modal ---------- */

export function Sheet({ title, onClose, children, footer, wide = false }) {
  const ref = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  // Solo al abrir/cerrar: si dependiera de onClose, cada re-render movería el foco mientras escribes.
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && closeRef.current()
    window.addEventListener('keydown', onKey)
    const previous = document.activeElement
    ref.current?.querySelector('input, select, button:not(.sheet-close)')?.focus()
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [])

  return (
    <div className="sheet-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`sheet ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="sheet-head">
          <h3 className="grow truncate">{title}</h3>
          <button className="icon-btn sheet-close" onClick={onClose} aria-label="Cerrar">
            <X size={16} />
          </button>
        </div>
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </div>
    </div>
  )
}

/* ---------- Notificaciones ---------- */

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const push = useCallback((toast) => {
    const id = Math.random().toString(36).slice(2)
    setToasts((list) => [...list.slice(-3), { id, ...toast }])
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), toast.duration || 5000)
  }, [])
  const dismiss = (id) => setToasts((list) => list.filter((t) => t.id !== id))
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => {
          const Icon = { error: XCircle, success: CheckCircle2, info: Info }[t.tone || 'info']
          const color = { error: 'var(--red)', success: 'var(--green)', info: 'var(--accent)' }[t.tone || 'info']
          return (
            <div key={t.id} className="toast" role="status">
              <Icon size={20} style={{ color, flex: 'none' }} aria-hidden="true" />
              <div className="grow">
                <b>{t.title}</b>
                {t.body}
              </div>
              <button className="icon-btn" onClick={() => dismiss(t.id)} aria-label="Cerrar notificación">
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)

export function initials(name = '') {
  return name.slice(0, 2).toUpperCase()
}
