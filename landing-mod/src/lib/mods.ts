import rawManifest from "./mods-manifest.json";

export interface ModItem {
  id: string;
  name: string;
  filename: string;
  size: string;
  sizeBytes: number;
  sha1: string;
  description: string;
  downloadUrl: string | null;
  modrinthId: string | null;
  category: string;
}

export const MODS_MANIFEST: ModItem[] = rawManifest as ModItem[];

/** Datos publicados del ZIP; se calculan desde su manifiesto, no desde la PC anfitriona. */
export const modpackManifest = {
  modCount: MODS_MANIFEST.length,
  jarBytes: MODS_MANIFEST.reduce((total, mod) => total + mod.sizeBytes, 0),
} as const;

export function formatBytes(bytes: number): string {
  return `${(bytes / 1024 / 1024).toLocaleString("es-AR", {
    maximumFractionDigits: 1,
  })} MiB`;
}

export const MOD_CATEGORIES = [
  "Todos",
  "Aventura & Mundo",
  "Construcción",
  "Optimización",
  "Utilidad & HUD",
  "Armas & Combate",
  "Comida & Agricultura",
  "Tecnología",
  "Librerías",
] as const;

export type ModCategory = (typeof MOD_CATEGORIES)[number];
