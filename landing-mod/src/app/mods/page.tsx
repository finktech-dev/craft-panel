import { ModCatalog } from "@/components/mod-catalog";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { modpackManifest } from "@/lib/mods";
import { serverConfig } from "@/lib/server-config";

export const metadata = {
  title: "Catálogo de Mods — Servidor Minecraft",
  description: `Lista completa de los ${modpackManifest.modCount} mods del ZIP con buscador y enlaces oficiales.`
};

export default function ModsPage() {
  return (
    <>
      <SiteHeader />
      <main className="page-wrapper">
        <ModCatalog />
      </main>
      <SiteFooter loader={serverConfig.loader} gameVersion={serverConfig.gameVersion} />
    </>
  );
}
