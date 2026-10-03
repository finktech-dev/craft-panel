import Link from "next/link";
import { ThemeToggle } from "./theme-toggle";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="brand" href="/">Servidor Minecraft</Link>
      <nav aria-label="Navegación principal">
        <Link href="/mods">Mods</Link>
        <Link href="/cambios">Cambios</Link>
        <Link href="/zip">Validador ZIP</Link>
        <Link href="/java">Java 21</Link>
        <ThemeToggle />
      </nav>
    </header>
  );
}
