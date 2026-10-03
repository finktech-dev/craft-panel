import { DownloadButton } from "@/components/download-button";
import { ServerLiveStatus } from "@/components/server-live-status";
import { SiteFooter } from "@/components/site-footer";
import { modpackManifest } from "@/lib/mods";
import { currentModpackRelease } from "@/lib/modpack-releases";
import { SiteHeader } from "@/components/site-header";
import { hasPublicDownload, serverConfig } from "@/lib/server-config";
import Link from "next/link";

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero" aria-labelledby="page-title">
          <div>
            <p className="eyebrow"><i />{serverConfig.gameVersion} · {serverConfig.loader}</p>
            <h1 id="page-title">Descargá.<br />Instalá. Jugá.</h1>
            <p className="intro">El modpack oficial con los {modpackManifest.modCount} mods y configuraciones listos para entrar.</p>
            
            <div className="hero-cta-group">
              <DownloadButton downloadUrl={serverConfig.downloadUrl} />
              <ServerLiveStatus address={serverConfig.address} />
            </div>

            <p className="download-status">
              {hasPublicDownload ? "Archivo modpack listo para descargar." : "El enlace de descarga se sincroniza automáticamente."}
            </p>
          </div>

          <div className="version-card" aria-label={`${currentModpackRelease.version}, ${serverConfig.gameVersion} con ${serverConfig.loader}`}>
            <div className="window-controls"><i /><i /><i /></div>
            <div>
              <p>LISTO PARA JUGAR · {currentModpackRelease.date}</p>
              <strong>{currentModpackRelease.version}</strong>
              <b>{currentModpackRelease.label}</b>
            </div>
            <small><i /> Modpack activo · {modpackManifest.modCount} mods · {serverConfig.loader}</small>
          </div>
        </section>

        {/* Sección de Actualizaciones y Mod Propio */}
        <section className="updates-homepage-section" aria-labelledby="updates-title">
          <div className="updates-homepage-header">
            <div>
              <p className="eyebrow"><i />ACTUALIZACIÓN RECIENTE · {currentModpackRelease.date}</p>
              <h2 id="updates-title">Novedades del Servidor</h2>
            </div>
            <Link href="/cambios" className="updates-view-history">
              Ver registro completo en /cambios →
            </Link>
          </div>

          <div className="updates-homepage-grid">
            {/* Tarjeta destacada del Mod propio */}
            <article className="featured-mod-card">
              <div className="featured-mod-tag">
                <span>MOD PROPIO EXCLUSIVO</span>
                <span className="featured-badge">v1.1.0</span>
              </div>
              <h3>Point Blank Armory &amp; Durability</h3>
              <p className="featured-mod-desc">
                Desarrollado a medida para nuestro servidor. Añade desgaste balístico, durabilidad y mantenimiento al arsenal táctico de Vic&apos;s Point Blank, integrando mecánicas de supervivencia y preparación militar.
              </p>
              <ul className="featured-mod-features">
                <li>
                  <strong>⚙ Desgaste y Encasquillamiento:</strong> Cada disparo acumula fatiga. La suciedad acumulada por uso y la lluvia elevan el riesgo de atasco de cerrojo.
                </li>
                <li>
                  <strong>🔧 Desatasco Táctico:</strong> Acción configurable en Controles (<kbd>G</kbd>) para ciclar la corredera y expulsar manualmente vainas trabadas en combate.
                </li>
                <li>
                  <strong>🏹 Mesa de Flechería Oficial:</strong> Mesa de mantenimiento interactiva para limpiar ánimas con baquetas, lubricar y aplicar kits de servicio militar o reacondicionamiento.
                </li>
                <li>
                  <strong>🏷 Sellos de Calidad y Series:</strong> Calibrá tus cajas de munición con sellos Económico, Estándar o Match, y alterá el número de serie de tus armas con el Raspador.
                </li>
              </ul>
              <div className="featured-mod-footer">
                <span className="mod-compat-pill">✔ NeoForge 21.1.250 · Java 21</span>
                <Link href="/mods" className="featured-mod-link">Ver en catálogo de mods →</Link>
              </div>
            </article>

            {/* Tarjeta de registro de versión */}
            <article className="release-log-card">
              <div className="release-log-head">
                <div>
                  <span className="release-version-pill">{currentModpackRelease.version}</span>
                  <span className="release-date-text">{currentModpackRelease.date}</span>
                </div>
                <span className="release-tag-pill">{currentModpackRelease.badge || "Release"}</span>
              </div>
              <h4>{currentModpackRelease.label}</h4>
              <p className="release-status-text">
                {currentModpackRelease.requiresRedownload
                  ? "⚠ Requiere actualizar el ZIP antes de conectar al servidor."
                  : "✔ Compatible con la instalación previa."}
              </p>
              <ul className="release-changes-list">
                {currentModpackRelease.changes.map((change, i) => (
                  <li key={i}>{change}</li>
                ))}
              </ul>
              <div className="release-card-footer">
                <Link href="/zip" className="release-verify-link">Comprobar con el Validador de ZIP →</Link>
              </div>
            </article>
          </div>
        </section>

        <section className="screens-nav-section" aria-label="Secciones del servidor">
          <div className="screens-nav-grid">
            <Link href="/zip" className="screen-card">
              <span className="screen-tag">01 · HERRAMIENTA</span>
              <h3>Validador de ZIP</h3>
              <p>Subí tu archivo .zip o carpeta mods y comprobá al instante si te falta algún archivo para entrar.</p>
              <span className="screen-link-text">Abrir validador →</span>
            </Link>

            <Link href="/mods" className="screen-card">
              <span className="screen-tag">02 · CATÁLOGO</span>
              <h3>Descargar Mods</h3>
              <p>Explorá los {modpackManifest.modCount} mods del ZIP con buscador instantáneo, categorías y enlaces oficiales cuando estén disponibles.</p>
              <span className="screen-link-text">Ver catálogo de mods →</span>
            </Link>

            <Link href="/java" className="screen-card">
              <span className="screen-tag">03 · REQUISITO</span>
              <h3>Instalar Java 21</h3>
              <p>Descargá el instalador oficial de Java 21 LTS de Adoptium necesario para que el juego abra sin errores.</p>
              <span className="screen-link-text">Descargar Java 21 →</span>
            </Link>

            <Link href="/cambios" className="screen-card">
              <span className="screen-tag">04 · VERSIONES</span>
              <h3>Qué cambió</h3>
              <p>Revisá la versión activa, los cambios desde el pack anterior y si tenés que volver a descargarlo.</p>
              <span className="screen-link-text">Ver historial →</span>
            </Link>
          </div>
        </section>
      </main>
      <SiteFooter loader={serverConfig.loader} gameVersion={serverConfig.gameVersion} />
    </>
  );
}
