export const serverConfig = {
  gameVersion: "Minecraft Java 1.21.1",
  loader: "NeoForge",
  downloadUrl: process.env.NEXT_PUBLIC_MODPACK_DOWNLOAD_URL?.trim() ?? "",
  changelogUrl: process.env.NEXT_PUBLIC_MODPACK_CHANGELOG_URL?.trim() || "https://docs.google.com/document/d/1vvTB8a44txZExpB45Iq77vi64njjB69tYByTQR-YzZw/edit",
  address: process.env.NEXT_PUBLIC_SERVER_ADDRESS?.trim() || "della-parts.tun.ply.gg"
} as const;

export const hasPublicDownload = Boolean(serverConfig.downloadUrl);
