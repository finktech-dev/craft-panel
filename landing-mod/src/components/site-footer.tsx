export function SiteFooter({ loader, gameVersion }: { loader: string; gameVersion: string }) {
  return <footer><span>Servidor Minecraft</span><span>{loader} · {gameVersion}</span></footer>;
}
