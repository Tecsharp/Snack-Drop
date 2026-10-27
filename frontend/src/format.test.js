import { describe, expect, it } from 'vitest'
import { describeParams, formatBytes, formatDate, formatDuration, formatTime, isActive, statusLabel } from './format.js'

describe('format', () => {
  it('formatBytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.50 KB')
    expect(formatBytes(3.97 * 1024 ** 3)).toBe('3.97 GB')
    expect(formatBytes(-1)).toBe('—')
  })

  it('formatDuration', () => {
    expect(formatDuration('2026-01-01T00:00:00Z', '2026-01-01T00:46:04Z')).toBe('46:04')
    expect(formatDuration('2026-01-01T00:00:00Z', '2026-01-01T02:15:39Z')).toBe('2:15:39')
    expect(formatDuration(null)).toBe('')
  })

  it('formatDate en español', () => {
    // Fecha local (sin zona) para que la prueba no dependa del huso horario.
    expect(formatDate('2026-11-03T01:50:49')).toBe('3 de noviembre del 2026, 01:50')
    expect(formatDate('2026-10-11T13:05:00')).toBe('11 de octubre del 2026, 13:05')
    expect(formatDate(null)).toBe('—')
    expect(formatTime('2026-10-11T09:04:07', true)).toBe('09:04:07')
  })

  it('status helpers', () => {
    expect(statusLabel('processing')).toBe('Procesando')
    expect(isActive({ status: 'uploading' })).toBe(true)
    expect(isActive({ status: 'done' })).toBe(false)
  })

  it('describeParams genérico desde el catálogo', () => {
    const op = {
      title: 'Separar PDF',
      defaults: { mode: 'each_page', ranges: '' },
      schema: { properties: { mode: { title: 'Separar', enum: ['each_page', 'ranges'], labels: { ranges: 'Por rangos' } }, ranges: { title: 'Rangos' } } },
    }
    expect(describeParams('pdf.split', { mode: 'ranges', ranges: '1-3' }, op)).toBe('Separar PDF · Por rangos · rangos 1-3')
    const protect = { title: 'Proteger', defaults: {}, schema: { properties: { password: { title: 'Contraseña', format: 'password' } } } }
    expect(describeParams('pdf.protect', { password: '••••' }, protect)).toBe('Proteger')
  })

  it('describeParams', () => {
    expect(describeParams('image.convert', { format: 'webp', quality: 70, max_width: 1920 })).toBe(
      'WEBP · calidad 70 · ≤1920px ancho',
    )
    expect(describeParams('pdf.compress', { level: 'high', grayscale: true })).toBe(
      'Compresión máxima · escala de grises',
    )
  })
})
