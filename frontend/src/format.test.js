import { describe, expect, it } from 'vitest'
import { describeParams, formatBytes, formatDuration, isActive, statusLabel } from './format.js'

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

  it('status helpers', () => {
    expect(statusLabel('processing')).toBe('Procesando')
    expect(isActive({ status: 'uploading' })).toBe(true)
    expect(isActive({ status: 'done' })).toBe(false)
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
