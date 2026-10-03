import Link from "next/link";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { currentModpackRelease, modpackReleases } from "@/lib/modpack-releases";
import { serverConfig } from "@/lib/server-config";

export default function CambiosPage() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="page-intro" aria-labelledby="page-title">
          <p className="eyebrow"><i />HISTORIAL DEL MODPACK</p>
          <h1 id="page-title">Qué cambió en el pack.</h1>
          <p>Antes de entrar, comprobá si tu instalación coincide con la versión activa.</p>
        </section>

        <section className="highlights" aria-label="Versión activa">
          <article>
            <span>VERSIÓN ACTUAL · {currentModpackRelease.date}</span>
            <h2>{currentModpackRelease.version}</h2>
            <p>{currentModpackRelease.label}</p>
          </article>
          <article>
            <span>DESCARGA</span>
            <h2>{currentModpackRelease.requiresRedownload ? "Actualizá el ZIP" : "No hace falta bajar de nuevo"}</h2>
            <p>{currentModpackRelease.requiresRedownload ? "Si venías jugando con un ZIP anterior, descargalo otra vez antes de entrar." : "Tu instalación anterior sigue siendo compatible."}</p>
          </article>
          <article>
            <span>HISTORIAL COMPLETO</span>
            <h2>En Drive</h2>
            <p>El documento se actualiza en el mismo folder que el modpack, sin cambiar su enlace.</p>
          </article>
        </section>

        <section className="steps" aria-label="Cambios por versión">
          <div>
            <p className="eyebrow"><i />RELEASES</p>
            <h2>Notas de versión.</h2>
          </div>
          <ol>
            {modpackReleases.map((release) => (
              <li key={release.version}>
                <span>{release.version}</span>
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "8px", marginBottom: "8px" }}>
                    <h3 style={{ margin: 0 }}>{release.label}</h3>
                    <time style={{ font: "600 13px var(--font-mono)", color: "var(--blue)" }}>{release.date}</time>
                  </div>
                  {release.changes.map((change) => <p key={change}>{change}</p>)}
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="next-actions" aria-label="Acciones del modpack">
          <Link href="/">Descargar el modpack <small>Volvé al inicio para bajar el ZIP actual.</small></Link>
          <a href={serverConfig.changelogUrl} target="_blank" rel="noreferrer">Abrir historial en Drive <small>Ver o editar el registro completo de cambios.</small></a>
        </section>
      </main>
      <SiteFooter loader={serverConfig.loader} gameVersion={serverConfig.gameVersion} />
    </>
  );
}
