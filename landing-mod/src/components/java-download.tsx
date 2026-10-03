"use client";

const TEMURIN_WINDOWS_MSI =
  "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.6+7/OpenJDK21U-jdk_x64_windows_hotspot_21.0.6_7.msi";
const TEMURIN_MACOS_PKG =
  "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.6+7/OpenJDK21U-jdk_x64_mac_hotspot_21.0.6_7.pkg";
const TEMURIN_LINUX_TAR =
  "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.6+7/OpenJDK21U-jdk_x64_linux_hotspot_21.0.6_7.tar.gz";

export function JavaDownload() {
  return (
    <section className="java-page-section">
      <div className="section-head">
        <p className="eyebrow">Requisito Obligatorio</p>
        <h1>Descargar Java 21</h1>
        <p className="intro">
          Minecraft 1.21.1 y NeoForge requieren <strong>Java 21</strong> para ejecutarse.
        </p>
      </div>

      <div className="java-hero-box is-single">
        <div className="java-hero-content">
          <div className="java-tag">DISTRIBUCIÓN OFICIAL LTS RECOMENDADA</div>
          <h2>Eclipse Temurin OpenJDK 21</h2>
          <p>
            Instalador oficial de 64 bits para Windows. Seguro, optimizado y sin software adicional.
          </p>
          <div className="java-actions">
            <a
              href={TEMURIN_WINDOWS_MSI}
              className="button button-primary java-main-btn"
              download
            >
              <span>Descargar Java 21 para Windows (.msi)</span>
              <small>Versión 21.0.6 LTS · 170 MB</small>
            </a>
          </div>
          <div className="other-platforms">
            <span>Otros sistemas:</span>
            <a href={TEMURIN_MACOS_PKG} target="_blank" rel="noreferrer">
              macOS (.pkg)
            </a>
            <span className="dot-sep">·</span>
            <a href={TEMURIN_LINUX_TAR} target="_blank" rel="noreferrer">
              Linux (.tar.gz)
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
