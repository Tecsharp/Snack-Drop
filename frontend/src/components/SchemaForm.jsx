import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Segmented, Toggle } from '../ui.jsx'

/**
 * Formulario generado a partir del JSON Schema de cada operación del catálogo.
 * enum corto → control segmentado · enum largo → menú · boolean → interruptor ·
 * entero acotado → deslizador · string → texto (o contraseña).
 * Con muchos campos, los menos importantes quedan tras «Más opciones».
 */

const VISIBLE = 4

function unwrap(prop) {
  if (prop.anyOf) {
    const inner = prop.anyOf.find((p) => p.type !== 'null') || {}
    return { ...inner, ...prop, anyOf: undefined, nullable: true }
  }
  return prop
}

function optionLabel(p, value) {
  return p.labels?.[String(value)] || String(value)
}

function Field({ name, prop, value, onChange, required }) {
  const p = unwrap(prop)
  const label = p.title || name
  const help = p.description ? <span className="field-help">{p.description}</span> : null

  if (p.enum) {
    const short = !p.nullable && p.enum.length <= 3 && p.enum.every((o) => optionLabel(p, o).length <= 14)
    if (short) {
      return (
        <div className="field">
          <span>{label}</span>
          <Segmented
            full
            label={label}
            value={value}
            onChange={onChange}
            options={p.enum.map((o) => ({ value: o, label: optionLabel(p, o) }))}
          />
          {help}
        </div>
      )
    }
    return (
      <label className="field">
        {label}
        <select
          value={value === null || value === undefined ? '' : String(value)}
          onChange={(e) => {
            const raw = e.target.value
            if (raw === '') return onChange(null)
            onChange(p.type === 'integer' || p.type === 'number' ? Number(raw) : raw)
          }}
        >
          {p.nullable && <option value="">{p.placeholder || 'Ninguno'}</option>}
          {p.enum.map((o) => (
            <option key={String(o)} value={String(o)}>
              {optionLabel(p, o)}
            </option>
          ))}
        </select>
        {help}
      </label>
    )
  }

  if (p.type === 'integer' || p.type === 'number') {
    const { minimum: min, maximum: max } = p
    const slider = !p.nullable && p.type === 'integer' && min !== undefined && max !== undefined && max - min <= 100
    if (slider) {
      return (
        <label className="field">
          <span className="row between">
            {label}
            <b className="tnum" style={{ color: 'var(--label)' }}>{value}</b>
          </span>
          <input type="range" min={min} max={max} value={value ?? min} onChange={(e) => onChange(Number(e.target.value))} />
          {help}
        </label>
      )
    }
    return (
      <label className="field">
        {label}
        <input
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step={p.type === 'number' ? 'any' : 1}
          placeholder={p.placeholder || ''}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value === '' ? (p.nullable ? null : min ?? 0) : Number(e.target.value))}
        />
        {help}
      </label>
    )
  }

  const secret = p.format === 'password'
  return (
    <label className="field">
      <span>
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </span>
      <input
        type={secret ? 'password' : 'text'}
        autoComplete={secret ? 'new-password' : 'off'}
        maxLength={p.maxLength}
        placeholder={p.placeholder || ''}
        value={value ?? ''}
        required={required}
        onChange={(e) => onChange(e.target.value)}
      />
      {help}
    </label>
  )
}

export default function SchemaForm({ schema, values, onChange }) {
  const [more, setMore] = useState(false)
  const props = schema?.properties || {}
  const required = new Set(schema?.required || [])
  const names = Object.keys(props)
  if (!names.length) return <p className="caption" style={{ margin: 0 }}>Esta operación no necesita ajustes.</p>

  const isBool = (n) => unwrap(props[n]).type === 'boolean'
  const fields = names.filter((n) => !isBool(n))
  const toggles = names.filter(isBool)
  const primary = fields.filter((n, i) => i < VISIBLE || required.has(n))
  const advanced = fields.filter((n) => !primary.includes(n))
  const shownToggles = advanced.length && !more ? toggles.slice(0, 2) : toggles
  const hidden = advanced.length + toggles.length - shownToggles.length

  const render = (n) => (
    <Field key={n} name={n} prop={props[n]} value={values[n]} required={required.has(n)} onChange={(v) => onChange({ [n]: v })} />
  )

  return (
    <div className="param-grid">
      {primary.map(render)}
      {more && advanced.map(render)}
      {shownToggles.length > 0 && (
        <div className="toggles">
          {shownToggles.map((n) => (
            <Toggle
              key={n}
              label={props[n].title || n}
              help={props[n].description}
              checked={values[n]}
              onChange={(v) => onChange({ [n]: v })}
            />
          ))}
        </div>
      )}
      {hidden > 0 || more ? (
        <div className="span">
          <button type="button" className="disclosure" aria-expanded={more} onClick={() => setMore(!more)}>
            {more ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {more ? 'Menos opciones' : `Más opciones (${hidden})`}
          </button>
        </div>
      ) : null}
    </div>
  )
}
