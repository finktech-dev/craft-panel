import { ImageResponse } from "next/og";

export const alt = "Modpack del servidor";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#f7f7f5",
          color: "#0c1d3a",
          display: "flex",
          flexDirection: "column",
          height: "100%",
          justifyContent: "space-between",
          padding: "72px"
        }}
      >
        <div style={{ color: "#2459e8", display: "flex", fontSize: 24, letterSpacing: 3 }}>
          MINECRAFT JAVA 1.21.1 · NEOFORGE
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 82, fontWeight: 700, letterSpacing: -4 }}>
            Modpack del servidor
          </div>
          <div style={{ color: "#60708b", display: "flex", fontSize: 34, marginTop: 20 }}>
            Descargá, instalá y entrá.
          </div>
        </div>
        <div
          style={{
            alignItems: "center",
            borderTop: "2px solid #dbe0ea",
            display: "flex",
            fontSize: 27,
            justifyContent: "space-between",
            paddingTop: 28
          }}
        >
          <span>MOD INCLUIDO</span>
          <strong>Immersive Melodies</strong>
        </div>
      </div>
    ),
    size
  );
}
