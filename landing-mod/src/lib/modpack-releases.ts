export type ModpackRelease = {
  version: string;
  label: string;
  date: string;
  badge?: string;
  changes: readonly string[];
  requiresRedownload: boolean;
};

// Esta es la única fuente para la versión que muestra la landing.
// Al publicar un ZIP nuevo en Drive, agregá la nueva release al inicio.
export const modpackReleases: readonly ModpackRelease[] = [
  {
    version: "v1.1",
    label: "Point Blank Armory & Mantenimiento",
    date: "30 de Septiembre, 2026",
    badge: "Nuevo Mod Propio",
    changes: [
      "Se integró el mod propio 'Point Blank Armory & Durability' (v1.1.0) al modpack.",
      "Sistema de durabilidad y desgaste por disparo en todo el arsenal de Point Blank.",
      "Mecánica de atasco por suciedad, humedad/lluvia y calidad del lote de munición.",
      "Acción de ciclar cerrojo / desatascar manual (tecla configurable en Controles).",
      "Kits de mantenimiento militar, baquetas de limpieza, aceites y reacondicionamiento en Mesa de Flechería.",
      "Sellos de lote (Económico, Estándar, Match) para clasificar y modificar balística.",
      "Raspador de número de serie y trazabilidad de armas.",
      "Parches de estabilidad mixin contra fallos en animaciones y draw de armas de Point Blank."
    ],
    requiresRedownload: true
  },
  {
    version: "v1.0",
    label: "Base inicial",
    date: "22 de Septiembre, 2026",
    badge: "Lanzamiento",
    changes: [
      "Se establece esta versión como punto de partida del historial.",
      "El listado de mods se toma del manifiesto que acompaña al ZIP publicado."
    ],
    requiresRedownload: true
  }
];

export const currentModpackRelease = modpackReleases[0];
