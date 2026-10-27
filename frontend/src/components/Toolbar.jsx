export default function Toolbar({ title, subtitle, children }) {
  return (
    <header className="toolbar">
      <div className="grow" style={{ minWidth: 0 }}>
        <h1 className="truncate">{title}</h1>
        {subtitle && <div className="subtitle truncate">{subtitle}</div>}
      </div>
      {children && <div className="toolbar-actions">{children}</div>}
    </header>
  )
}
