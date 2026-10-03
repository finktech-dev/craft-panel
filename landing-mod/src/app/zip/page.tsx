import { ModValidator } from "@/components/mod-validator";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { serverConfig } from "@/lib/server-config";

export const metadata = {
  title: "Validador de ZIP y Mods — Servidor Minecraft",
  description: "Comprobá si te falta algún mod subiendo tu archivo ZIP o carpeta mods."
};

export default function ZipPage() {
  return (
    <>
      <SiteHeader />
      <main className="page-wrapper">
        <ModValidator />
      </main>
      <SiteFooter loader={serverConfig.loader} gameVersion={serverConfig.gameVersion} />
    </>
  );
}
