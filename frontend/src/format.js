export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return i === 0 ? `${value} B` : `${value.toFixed(2)} ${units[i]}`
}

const MONTHS = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]
const pad2 = (n) => String(n).padStart(2, '0')

/** «3 de noviembre del 2026, 01:50» en la zona horaria del navegador. */
export function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getDate()} de ${MONTHS[d.getMonth()]} del ${d.getFullYear()}, ${formatTime(d)}`
}

/** «01:50:07», formato de 24 horas. */
export function formatTime(value, seconds = false) {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const base = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  return seconds ? `${base}:${pad2(d.getSeconds())}` : base
}

export function formatDuration(startIso, endIso) {
  if (!startIso) return ''
  const start = new Date(startIso).getTime()
  const end = endIso ? new Date(endIso).getTime() : Date.now()
  const s = Math.max(0, Math.round((end - start) / 1000))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`
}

export const STATUS_LABELS = {
  queued: 'En cola',
  assigned: 'Asignado',
  downloading: 'Descargando',
  processing: 'Procesando',
  uploading: 'Subiendo',
  done: 'Completado',
  failed: 'Falló',
  cancelled: 'Cancelado',
  online: 'En línea',
  offline: 'Desconectado',
  paused: 'Pausado',
}

export const statusLabel = (s) => STATUS_LABELS[s] || s

export const ACTIVE = ['queued', 'assigned', 'downloading', 'processing', 'uploading']
export const isActive = (job) => ACTIVE.includes(job.status)

export function describeParams(operation, params = {}) {
  if (operation === 'image.convert') {
    const parts = [String(params.format || 'webp').toUpperCase()]
    if (params.lossless) parts.push('sin pérdida')
    else if (params.quality) parts.push(`calidad ${params.quality}`)
    if (params.max_width) parts.push(`≤${params.max_width}px ancho`)
    if (params.max_height) parts.push(`≤${params.max_height}px alto`)
    return parts.join(' · ')
  }
  if (operation === 'pdf.compress') {
    const level = { low: 'ligera', medium: 'media', high: 'máxima' }[params.level] || params.level
    return `Compresión ${level}${params.grayscale ? ' · escala de grises' : ''}`
  }
  return operation
}
