import { JavaDownload } from "@/components/java-download";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { serverConfig } from "@/lib/server-config";

export const metadata = {
  title: "Java 21 — Servidor Minecraft",
  description: "Descarga oficial de Java 21 (Temurin OpenJDK LTS) para Minecraft 1.21.1 NeoForge."
};

export default function JavaPage() {
  return (
    <>
      <SiteHeader />
      <main className="page-wrapper">
        <JavaDownload />
      </main>
      <SiteFooter loader={serverConfig.loader} gameVersion={serverConfig.gameVersion} />
    </>
  );
}
