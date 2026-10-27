import { useCallback, useEffect, useState } from 'react'

/** Colores de acento estilo macOS: `tint` para texto/iconos, `fill` (más oscuro) para botones con texto blanco (≥4.5:1). */
export const ACCENTS = {
  purple: { name: 'Morado', tint: ['#9B44CF', '#D08AF6'], fill: '#8A3DBE' },
  blue: { name: 'Azul', tint: ['#0066D6', '#0A84FF'], fill: '#0062CC' },
  pink: { name: 'Rosa', tint: ['#D12A55', '#FF375F'], fill: '#C7254E' },
  orange: { name: 'Naranja', tint: ['#B35300', '#FF9F0A'], fill: '#B35300' },
  green: { name: 'Verde', tint: ['#1A7F37', '#30D158'], fill: '#1A7F37' },
  graphite: { name: 'Grafito', tint: ['#636366', '#98989D'], fill: '#5A5A5F' },
}

export const THEMES = {
  aqua: { name: 'Aqua', description: 'Estilo macOS / iPadOS: translúcido, redondeado, claro u oscuro.' },
  industrial: { name: 'Industrial', description: 'Brutalismo suizo: papel, tinta negra, rojo y rejilla rígida.' },
}

const KEY = 'snackdrop.appearance'
const DEFAULTS = { theme: 'aqua', mode: 'system', accent: 'purple' }

function load() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }
  } catch {
    return DEFAULTS
  }
}

function apply({ theme, mode, accent }) {
  const root = document.documentElement
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
  const resolved = theme === 'industrial' ? 'light' : mode === 'system' ? (prefersDark ? 'dark' : 'light') : mode
  const a = ACCENTS[accent] || ACCENTS.purple
  root.dataset.theme = THEMES[theme] ? theme : 'aqua'
  root.dataset.mode = resolved
  root.style.setProperty('--accent', resolved === 'dark' ? a.tint[1] : a.tint[0])
  root.style.setProperty('--accent-fill', a.fill)
  // Texto de acento sobre fondos teñidos: el relleno (más oscuro) en claro, el tono en oscuro.
  root.style.setProperty('--accent-text', resolved === 'dark' ? a.tint[1] : a.fill)
  root.style.colorScheme = resolved
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'dark' ? '#1e1e20' : '#f5f5f7')
}

// Se aplica antes del primer render para evitar el destello de tema incorrecto.
apply(load())

export function useAppearance() {
  const [appearance, setAppearance] = useState(load)

  useEffect(() => {
    apply(appearance)
    localStorage.setItem(KEY, JSON.stringify(appearance))
    if (appearance.mode !== 'system') return undefined
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => apply(appearance)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [appearance])

  const update = useCallback((patch) => setAppearance((prev) => ({ ...prev, ...patch })), [])
  return [appearance, update]
}
