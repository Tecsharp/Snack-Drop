import { LogOut, Monitor, Moon, Sun } from 'lucide-react'
import Toolbar from '../components/Toolbar.jsx'
import { ACCENTS, THEMES } from '../appearance.js'
import { initials, Segmented } from '../ui.jsx'
import ChangePassword from './ChangePassword.jsx'

export default function SettingsPage({ me, onMe, appearance, setAppearance, onLogout }) {
  const industrial = appearance.theme === 'industrial'
  return (
    <>
      <Toolbar title="Ajustes" />
      <div className="page narrow">
        <section className="section" aria-labelledby="appearance-title">
          <div className="section-head">
            <h2 id="appearance-title">Apariencia</h2>
          </div>
          <div className="theme-cards">
            {Object.entries(THEMES).map(([id, t]) => (
              <button key={id} type="button" className="theme-card" aria-pressed={appearance.theme === id} onClick={() => setAppearance({ theme: id })}>
                <div className={`theme-preview ${id}`} aria-hidden="true">
                  <div className="pv-side" />
                  <div className="pv-main">
                    {id === 'industrial' ? 'SNACK' : null}
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
                <div>
                  <b>{t.name}</b>
                  <div className="caption">{t.description}</div>
                </div>
              </button>
            ))}
          </div>
          <div className="group">
            <div className="list-row">
              <span className="grow">Modo</span>
              {industrial ? (
                <span className="caption">El tema Industrial siempre es claro</span>
              ) : (
                <Segmented
                  label="Modo de color"
                  value={appearance.mode}
                  onChange={(mode) => setAppearance({ mode })}
                  options={[
                    { value: 'system', label: <><Monitor size={13} aria-hidden="true" /> Sistema</> },
                    { value: 'light', label: <><Sun size={13} aria-hidden="true" /> Claro</> },
                    { value: 'dark', label: <><Moon size={13} aria-hidden="true" /> Oscuro</> },
                  ]}
                />
              )}
            </div>
            {!industrial && (
              <div className="list-row">
                <span className="grow">Color de acento</span>
                <div className="swatches" role="group" aria-label="Color de acento">
                  {Object.entries(ACCENTS).map(([id, a]) => (
                    <button
                      key={id}
                      type="button"
                      className="swatch"
                      title={a.name}
                      aria-label={a.name}
                      aria-pressed={appearance.accent === id}
                      style={{ background: a.fill, color: a.fill }}
                      onClick={() => setAppearance({ accent: id })}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
          <p className="footnote">La apariencia se guarda en este navegador.</p>
        </section>

        <section className="section" aria-labelledby="account-title">
          <div className="section-head">
            <h2 id="account-title">Cuenta</h2>
          </div>
          <div className="group">
            <div className="list-row">
              <span className="avatar" aria-hidden="true">{initials(me.username)}</span>
              <div className="grow">
                <div className="title">{me.username}</div>
                <div className="caption">{me.role === 'admin' ? 'Administrador' : 'Usuario'}</div>
              </div>
              <button className="btn destructive" onClick={onLogout}>
                <LogOut size={15} aria-hidden="true" /> Cerrar sesión
              </button>
            </div>
          </div>
        </section>

        <section className="section" aria-labelledby="password-title">
          <div className="section-head">
            <h2 id="password-title">Contraseña</h2>
          </div>
          <ChangePassword me={me} onDone={onMe} />
        </section>
      </div>
    </>
  )
}
