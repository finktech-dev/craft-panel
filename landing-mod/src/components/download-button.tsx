"use client";

import { useState } from "react";

type DownloadButtonProps = {
  downloadUrl: string;
};

export function DownloadButton({ downloadUrl }: DownloadButtonProps) {
  const [message, setMessage] = useState("");

  if (downloadUrl) {
    return (
      <a className="button button-primary" href={downloadUrl}>
        <span>Descargar modpack</span>
        <small>Archivo .zip</small>
      </a>
    );
  }

  return (
    <>
      <button className="button button-primary" type="button" onClick={() => setMessage("El enlace de descarga todavía no está publicado.")}>
        <span>Descargar modpack</span>
        <small>Archivo .zip</small>
      </button>
      {message ? <p className="button-message" role="status">{message}</p> : null}
    </>
  );
}
