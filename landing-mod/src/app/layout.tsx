import type { Metadata } from "next";
import { DM_Mono, Inter } from "next/font/google";
import "@/styles/globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const dmMono = DM_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

function getSiteUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  if (envUrl) {
    const clean = envUrl.replace(/\/+$/, "");
    return clean.startsWith("http://") || clean.startsWith("https://") ? clean : `https://${clean}`;
  }
  const prodUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL?.trim();
  if (prodUrl) {
    return `https://${prodUrl.replace(/\/+$/, "")}`;
  }
  const vercelUrl = process.env.NEXT_PUBLIC_VERCEL_URL?.trim() || process.env.VERCEL_URL?.trim();
  if (vercelUrl) {
    return `https://${vercelUrl.replace(/\/+$/, "")}`;
  }
  return "https://example.com";
}

const publicSiteUrl = getSiteUrl();

export const metadata: Metadata = {
  metadataBase: new URL(publicSiteUrl),
  title: "Modpack del servidor",
  description: "Descargá el modpack, instalalo y entrá con Minecraft Java 1.21.1 y NeoForge.",
  openGraph: {
    type: "website",
    locale: "es_AR",
    title: "Modpack del servidor",
    description: "Todo lo necesario para entrar.",
    siteName: "Modpack del servidor"
  },
  twitter: {
    card: "summary_large_image",
    title: "Modpack del servidor",
    description: "Todo lo necesario para entrar."
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var s=localStorage.getItem('theme');var d=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';var t=s||d;document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`
          }}
        />
      </head>
      <body className={`${inter.variable} ${dmMono.variable}`}>{children}</body>
    </html>
  );
}
