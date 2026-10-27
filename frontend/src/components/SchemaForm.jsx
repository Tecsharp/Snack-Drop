/**
 * Formulario generado a partir del JSON Schema de cada operación del catálogo.
 * Soporta: enum (select), boolean (checkbox), integer/number (slider o número), string (texto o contraseña)
 * y campos opcionales (anyOf con null).
 */

function unwrap(prop) {
  if (prop.anyOf) {
    const inner = prop.anyOf.find((p) => p.type !== 'null') || {}
    return { ...inner, ...prop, anyOf: undefined, nullable: true }
  }
  return prop
}

function Field({ name, prop, value, onChange, required }) {
  const p = unwrap(prop)
  const label = p.title || name
  const labels = p.labels || {}
  const help = p.description ? <span className="field-help">{p.description}</span> : null

  if (p.enum) {
    return (
      <label>
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
          {p.enum.map((opt) => (
            <option key={String(opt)} value={String(opt)}>
              {labels[String(opt)] || String(opt)}
            </option>
          ))}
        </select>
        {help}
      </label>
    )
  }

  if (p.type === 'boolean') {
    return (
      <label className="check" title={p.description || ''}>
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} /> {label}
      </label>
    )
  }

  if (p.type === 'integer' || p.type === 'number') {
    const min = p.minimum
    const max = p.maximum
    const slider = !p.nullable && min !== undefined && max !== undefined && max - min <= 100 && p.type === 'integer'
    if (slider) {
      return (
        <label>
          {label}: <b className="field-value">{value}</b>
          <input type="range" min={min} max={max} value={value ?? min} onChange={(e) => onChange(Number(e.target.value))} />
          {help}
        </label>
      )
    }
    return (
      <label>
        {label}
        <input
          type="number"
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
    <label>
      {label}
      {required ? ' *' : ''}
      <input
        type={secret ? 'password' : 'text'}
        autoComplete={secret ? 'new-password' : 'off'}
        maxLength={p.maxLength}
        placeholder={p.placeholder || ''}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      />
      {help}
    </label>
  )
}

export default function SchemaForm({ schema, values, onChange }) {
  const props = schema?.properties || {}
  const required = new Set(schema?.required || [])
  const names = Object.keys(props)
  if (!names.length) return <p className="muted small">Esta operación no necesita ajustes.</p>
  return (
    <div className="param-grid">
      {names.map((name) => (
        <Field
          key={name}
          name={name}
          prop={props[name]}
          value={values[name]}
          required={required.has(name)}
          onChange={(v) => onChange({ [name]: v })}
        />
      ))}
    </div>
  )
}
