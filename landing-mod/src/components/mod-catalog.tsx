"use client";

import { useState, useMemo } from "react";
import { formatBytes, MODS_MANIFEST, MOD_CATEGORIES, modpackManifest, ModCategory } from "@/lib/mods";
import { serverConfig } from "@/lib/server-config";

export function ModCatalog() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<ModCategory>("Todos");
  const [sortBy, setSortBy] = useState<"name" | "size">("name");
  const [copiedFilename, setCopiedFilename] = useState<string | null>(null);

  const copyFilename = (fn: string) => {
    navigator.clipboard.writeText(fn);
    setCopiedFilename(fn);
    setTimeout(() => {
      setCopiedFilename((prev) => (prev === fn ? null : prev));
    }, 2000);
  };

  // Category counts
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { Todos: MODS_MANIFEST.length };
    MODS_MANIFEST.forEach((mod) => {
      counts[mod.category] = (counts[mod.category] || 0) + 1;
    });
    return counts;
  }, []);

  const filteredMods = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    let list = MODS_MANIFEST.filter((mod) => {
      const matchCat =
        selectedCategory === "Todos" || mod.category === selectedCategory;
      if (!matchCat) return false;
      if (!q) return true;
      return (
        mod.name.toLowerCase().includes(q) ||
        mod.filename.toLowerCase().includes(q) ||
        mod.description.toLowerCase().includes(q) ||
        mod.category.toLowerCase().includes(q)
      );
    });

    list = [...list].sort((a, b) => {
      if (sortBy === "name") {
        return a.name.localeCompare(b.name);
      }
      return b.sizeBytes - a.sizeBytes;
    });

    return list;
  }, [searchQuery, selectedCategory, sortBy]);

  return (
    <section className="catalog-section" id="catalogo" aria-labelledby="catalogo-title">
      <div className="section-head">
        <p className="eyebrow">Catálogo oficial</p>
        <h1 id="catalogo-title">Mods del Servidor</h1>
        <p className="intro">
          Explorá los {modpackManifest.modCount} mods incluidos en el ZIP para NeoForge 1.21.1. Podés buscar cualquier mod por nombre, categoría o función, y abrir su enlace oficial cuando esté disponible.
        </p>
      </div>

      <div className="catalog-summary-grid" aria-label="Resumen de estadísticas del catálogo">
        <div className="summary-card">
          <span className="summary-label">Mods en el ZIP</span>
          <strong>{modpackManifest.modCount}</strong>
          <small>Según el manifiesto publicado</small>
        </div>
        <div className="summary-card">
          <span className="summary-label">Archivos del ZIP</span>
          <strong>{formatBytes(modpackManifest.jarBytes)}</strong>
          <small>Suma de los .jar del manifiesto</small>
        </div>
        <div className="summary-card">
          <span className="summary-label">Cargador Oficial</span>
          <strong>{serverConfig.loader}</strong>
          <small>Minecraft Java 1.21.1</small>
        </div>
      </div>

      <div className="catalog-controls">
        <div className="search-box">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            placeholder="Buscar por nombre, archivo o descripción (ej: Create, armas, JEI)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
          {searchQuery && (
            <button
              type="button"
              className="clear-search-btn"
              onClick={() => setSearchQuery("")}
            >
              ✕
            </button>
          )}
        </div>

        <div className="sort-selector">
          <label htmlFor="sort-mods">Ordenar:</label>
          <select
            id="sort-mods"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "name" | "size")}
            className="sort-select"
          >
            <option value="name">Nombre (A - Z)</option>
            <option value="size">Tamaño (Mayor a menor)</option>
          </select>
        </div>
      </div>

      <div className="category-pills" role="tablist" aria-label="Filtrar por categoría">
        {MOD_CATEGORIES.map((cat) => {
          const count = categoryCounts[cat] || 0;
          const isActive = selectedCategory === cat;
          return (
            <button
              key={cat}
              type="button"
              className={`pill-btn ${isActive ? "is-active" : ""}`}
              onClick={() => setSelectedCategory(cat)}
            >
              <span>{cat}</span>
              <small>{count}</small>
            </button>
          );
        })}
      </div>

      <div className="catalog-meta">
        <p>
          Mostrando <strong>{filteredMods.length}</strong> de{" "}
          <strong>{MODS_MANIFEST.length}</strong> mods
          {selectedCategory !== "Todos" && ` en ${selectedCategory}`}
          {searchQuery && ` para "${searchQuery}"`}
        </p>
        {(searchQuery || selectedCategory !== "Todos") && (
          <button
            type="button"
            className="reset-filters-btn"
            onClick={() => {
              setSearchQuery("");
              setSelectedCategory("Todos");
            }}
          >
            Restablecer filtros
          </button>
        )}
      </div>

      {filteredMods.length === 0 ? (
        <div className="empty-catalog">
          <p>No se encontraron mods que coincidan con la búsqueda.</p>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => {
              setSearchQuery("");
              setSelectedCategory("Todos");
            }}
          >
            Ver todos los mods
          </button>
        </div>
      ) : (
        <div className="mods-grid">
          {filteredMods.map((mod) => (
            <article key={mod.filename} className="mod-card">
              <div className="mod-card-header">
                <span className="category-badge">{mod.category}</span>
                <span
                  className="size-badge"
                  title={`${mod.sizeBytes.toLocaleString("es-AR")} bytes exactos`}
                >
                  {mod.size}
                </span>
              </div>
              <h3 className="mod-name">{mod.name}</h3>
              <div className="mod-filename-row">
                <code className="mod-filename" title={mod.filename}>
                  {mod.filename}
                </code>
                <button
                  type="button"
                  className="copy-fn-btn"
                  onClick={() => copyFilename(mod.filename)}
                  title="Copiar nombre de archivo"
                  aria-label={`Copiar ${mod.filename}`}
                >
                  {copiedFilename === mod.filename ? "✓" : "📋"}
                </button>
              </div>
              <p className="mod-desc">{mod.description}</p>
              <div className="mod-card-footer">
                <div className="mod-footer-actions">
                  {mod.downloadUrl ? (
                    <a
                      href={mod.downloadUrl}
                      className="download-btn-card"
                      target="_blank"
                      rel="noreferrer"
                      download={mod.filename}
                    >
                      <span>📥 Descargar .jar</span>
                    </a>
                  ) : (
                    <span className="no-direct-download">Incluido en el ZIP</span>
                  )}
                  {mod.modrinthId && (
                    <a
                      href={`https://modrinth.com/mod/${mod.modrinthId}`}
                      className="modrinth-link-btn"
                      target="_blank"
                      rel="noreferrer"
                      title="Ver página oficial en Modrinth"
                      aria-label={`Ver ${mod.name} en Modrinth`}
                    >
                      ↗
                    </a>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
