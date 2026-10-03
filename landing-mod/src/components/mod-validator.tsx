"use client";

import { useState, useRef, ChangeEvent, DragEvent } from "react";
import JSZip from "jszip";
import { MODS_MANIFEST, ModItem } from "@/lib/mods";
import { serverConfig } from "@/lib/server-config";
import Link from "next/link";

interface ValidationResult {
  matched: ModItem[];
  missing: ModItem[];
  unrecognized: string[];
  totalChecked: number;
  sourceName: string;
}

export function ModValidator() {
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"missing" | "matched" | "unrecognized">("missing");
  const [isDragging, setIsDragging] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const compareFiles = (detectedFilenames: string[], sourceName: string): ValidationResult => {
    // Normalization helper
    const normalize = (s: string) =>
      s.toLowerCase().replace(/\.jar$/, "").replace(/[-_\.+]/g, "");

    const availableSet = new Set(detectedFilenames.map((f) => f.toLowerCase().trim()));
    const normalizedAvailable = new Map<string, string>();
    detectedFilenames.forEach((f) => {
      normalizedAvailable.set(normalize(f), f);
    });

    const matched: ModItem[] = [];
    const missing: ModItem[] = [];
    const usedFilenames = new Set<string>();

    MODS_MANIFEST.forEach((expectedMod) => {
      const expLow = expectedMod.filename.toLowerCase().trim();
      const expNorm = normalize(expectedMod.filename);

      if (availableSet.has(expLow)) {
        matched.push(expectedMod);
        usedFilenames.add(expLow);
      } else if (normalizedAvailable.has(expNorm)) {
        matched.push(expectedMod);
        const original = normalizedAvailable.get(expNorm)!;
        usedFilenames.add(original.toLowerCase().trim());
      } else {
        missing.push(expectedMod);
      }
    });

    const unrecognized = detectedFilenames.filter(
      (f) => !usedFilenames.has(f.toLowerCase().trim())
    );

    return {
      matched,
      missing,
      unrecognized,
      totalChecked: detectedFilenames.length,
      sourceName,
    };
  };

  const processZipFile = async (file: File) => {
    setIsAnalyzing(true);
    setError(null);
    setProgress(15);
    setStatusText("Leyendo archivo ZIP...");

    try {
      const buffer = await file.arrayBuffer();
      setProgress(40);
      setStatusText("Descomprimiendo índice de archivos...");

      const zip = await JSZip.loadAsync(buffer);
      setProgress(75);
      setStatusText("Verificando mods...");

      const jarNames: string[] = [];
      zip.forEach((relativePath, entry) => {
        if (!entry.dir && relativePath.toLowerCase().endsWith(".jar")) {
          // Extract just the file name
          const fileName = relativePath.split("/").pop() || relativePath;
          if (fileName.trim()) {
            jarNames.push(fileName.trim());
          }
        }
      });

      if (jarNames.length === 0) {
        throw new Error(
          "No se encontraron archivos .jar dentro del ZIP. Asegurate de que contenga la carpeta mods con los mods del servidor."
        );
      }

      setProgress(100);
      const res = compareFiles(jarNames, file.name);
      setResult(res);
      setActiveTab(res.missing.length > 0 ? "missing" : "matched");
    } catch (err: unknown) {
      console.error(err);
      setError(
        err instanceof Error
          ? err.message
          : "Ocurrió un error al leer el archivo ZIP. Verificá que no esté dañado."
      );
    } finally {
      setIsAnalyzing(false);
    }
  };

  const processFileList = (files: FileList | File[], sourceName: string) => {
    setIsAnalyzing(true);
    setError(null);
    setProgress(50);
    setStatusText("Analizando archivos seleccionados...");

    try {
      const jarNames: string[] = [];
      Array.from(files).forEach((f) => {
        if (f.name.toLowerCase().endsWith(".jar")) {
          jarNames.push(f.name.trim());
        }
      });

      if (jarNames.length === 0) {
        throw new Error(
          "No se detectaron archivos .jar en la carpeta o selección. Asegurate de seleccionar tu carpeta mods."
        );
      }

      setProgress(100);
      const res = compareFiles(jarNames, sourceName);
      setResult(res);
      setActiveTab(res.missing.length > 0 ? "missing" : "matched");
    } catch (err: unknown) {
      console.error(err);
      setError(
        err instanceof Error ? err.message : "Error al inspeccionar la carpeta de mods."
      );
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const first = e.dataTransfer.files[0];
      if (first.name.toLowerCase().endsWith(".zip")) {
        processZipFile(first);
      } else {
        processFileList(e.dataTransfer.files, "Archivos arrastrados");
      }
    }
  };

  const handleZipChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processZipFile(e.target.files[0]);
    }
  };

  const handleFolderChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFileList(e.target.files, "Carpeta mods local");
    }
  };

  const resetValidator = () => {
    setResult(null);
    setError(null);
    setIsAnalyzing(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (folderInputRef.current) folderInputRef.current.value = "";
  };

  const totalRequired = MODS_MANIFEST.length;
  const matchPercent = result
    ? Math.round((result.matched.length / totalRequired) * 100)
    : 0;

  return (
    <section className="validator-section" id="validador" aria-labelledby="validador-title">
      <div className="section-head">
        <p className="eyebrow">Diagnóstico automático</p>
        <h1 id="validador-title">Validador de Mods</h1>
        <p className="intro">
          Subí tu archivo <code>.zip</code> o seleccioná tu carpeta <code>mods</code>. Te diremos en el acto si te falta algún mod o si tenés todo listo para entrar.
        </p>
      </div>

      {!result && (
        <div
          className={`drop-zone ${isDragging ? "is-drag-over" : ""} ${isAnalyzing ? "is-loading" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleZipChange}
            accept=".zip"
            style={{ display: "none" }}
          />
          {/* Note: webkitdirectory allows folder selection in chromium/firefox */}
          <input
            type="file"
            ref={folderInputRef}
            onChange={handleFolderChange}
            multiple
            // @ts-expect-error webkitdirectory is standard non-standard attribute
            webkitdirectory=""
            style={{ display: "none" }}
          />

          <div className="drop-content">
            <span className="drop-icon">📦</span>
            <h3>Arrastrá acá tu archivo .zip o carpeta mods</h3>
            <p>El análisis se procesa de forma instantánea y 100% privada en tu navegador.</p>

            {isAnalyzing ? (
              <div className="loading-state">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <small>{statusText}</small>
              </div>
            ) : (
              <div className="drop-actions">
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  Seleccionar archivo .ZIP
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => folderInputRef.current?.click()}
                >
                  Seleccionar carpeta mods
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="validator-alert is-error">
          <strong>⚠️ No se pudo completar el análisis</strong>
          <p>{error}</p>
          <button type="button" className="retry-btn" onClick={resetValidator}>
            Intentar de nuevo
          </button>
        </div>
      )}

      {result && (
        <div className="validator-results">
          <div
            className={`status-banner ${
              result.missing.length === 0 ? "is-complete" : "is-incomplete"
            }`}
          >
            <div className="status-badge-icon">
              {result.missing.length === 0 ? "✅" : "⚠️"}
            </div>
            <div>
              <h3>
                {result.missing.length === 0
                  ? "¡Tu modpack está 100% completo!"
                  : `Te faltan ${result.missing.length} mods obligatorios`}
              </h3>
              <p>
                {result.missing.length === 0
                  ? "Tenés todos los mods sincronizados con el servidor. Ya podés conectarte a jugar."
                  : "El servidor rechazará la conexión si faltan estos archivos. Descargalos abajo o descargá el ZIP completo."}
              </p>
            </div>
            <div className="status-percent">
              <span>{matchPercent}%</span>
              <small>COMPATIBILIDAD</small>
            </div>
          </div>

          <div className="stats-row">
            <div className="stat-card">
              <span>REQUERIDOS</span>
              <strong>{totalRequired}</strong>
              <small>Mods del servidor</small>
            </div>
            <div className="stat-card is-success">
              <span>DETECTADOS</span>
              <strong>{result.matched.length}</strong>
              <small>Listos en tu cliente</small>
            </div>
            <div className={`stat-card ${result.missing.length > 0 ? "is-danger" : ""}`}>
              <span>FALTANTES</span>
              <strong>{result.missing.length}</strong>
              <small>{result.missing.length === 0 ? "Ninguno faltante" : "Necesarios para entrar"}</small>
            </div>
            <div className="stat-card">
              <span>ADICIONALES</span>
              <strong>{result.unrecognized.length}</strong>
              <small>Mods ajenos al servidor</small>
            </div>
          </div>

          <div className="result-controls">
            <div className="tab-buttons">
              <button
                type="button"
                className={`tab-btn ${activeTab === "missing" ? "is-active" : ""}`}
                onClick={() => setActiveTab("missing")}
              >
                Faltantes ({result.missing.length})
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === "matched" ? "is-active" : ""}`}
                onClick={() => setActiveTab("matched")}
              >
                Correctos ({result.matched.length})
              </button>
              {result.unrecognized.length > 0 && (
                <button
                  type="button"
                  className={`tab-btn ${activeTab === "unrecognized" ? "is-active" : ""}`}
                  onClick={() => setActiveTab("unrecognized")}
                >
                  Adicionales ({result.unrecognized.length})
                </button>
              )}
            </div>

            <button type="button" className="secondary-action-btn" onClick={resetValidator}>
              Analizar otro archivo
            </button>
          </div>

          <div className="tab-panel">
            {activeTab === "missing" && (
              <div>
                {result.missing.length === 0 ? (
                  <div className="empty-panel">
                    <p>🎉 ¡No te falta ningún mod! Podés iniciar el juego directamente.</p>
                  </div>
                ) : (
                  <div className="mod-cards-list">
                    <div className="list-tip">
                      <span>💡 Consejo:</span> Podés descargar cada archivo que te falta con un clic y pegarlo en tu carpeta <code>.minecraft/mods</code>.
                    </div>
                    {result.missing.map((mod) => (
                      <div key={mod.filename} className="mod-row is-missing">
                        <div className="mod-row-info">
                          <span className="category-tag">{mod.category}</span>
                          <strong>{mod.name}</strong>
                          <code>{mod.filename}</code>
                        </div>
                        <div className="mod-row-actions">
                          <span className="mod-size">{mod.size}</span>
                          {mod.downloadUrl ? (
                            <a
                              href={mod.downloadUrl}
                              className="download-pill"
                              target="_blank"
                              rel="noreferrer"
                              download={mod.filename}
                            >
                              📥 Descargar .jar
                            </a>
                          ) : (
                            <Link href="/mods" className="download-pill">
                              Ver en catálogo
                            </Link>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === "matched" && (
              <div className="mod-cards-list">
                {result.matched.map((mod) => (
                  <div key={mod.filename} className="mod-row is-matched">
                    <div className="mod-row-info">
                      <span className="category-tag">{mod.category}</span>
                      <strong>{mod.name}</strong>
                      <code>{mod.filename}</code>
                    </div>
                    <div className="mod-row-actions">
                      <span className="verified-badge">✓ Verificado</span>
                      <span className="mod-size">{mod.size}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === "unrecognized" && (
              <div className="mod-cards-list">
                <div className="list-tip is-warning">
                  <span>⚠️ Atención:</span> Estos archivos están en tu carpeta pero <strong>no pertenecen al servidor</strong>. Si experimentás cierres inesperados, desinstalalos o desactivalos.
                </div>
                {result.unrecognized.map((name) => (
                  <div key={name} className="mod-row is-extra">
                    <div className="mod-row-info">
                      <strong>Archivo no oficial</strong>
                      <code>{name}</code>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
