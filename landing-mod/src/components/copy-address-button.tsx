"use client";

import { useState } from "react";

export function CopyAddressButton({ address }: { address: string }) {
  const [copied, setCopied] = useState(false);

  async function copyAddress() {
    try {
      await navigator.clipboard.writeText(address);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback if clipboard API is restricted
      const el = document.createElement("textarea");
      el.value = address;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <button
      className={`copy-button ${copied ? "is-copied" : ""}`}
      type="button"
      onClick={copyAddress}
      aria-label="Copiar dirección de conexión"
      title="Copiar dirección IP al portapapeles"
    >
      <span className="copy-icon" aria-hidden="true">{copied ? "✓" : "📋"}</span>
      <span className="copy-text">{copied ? "¡Copiado!" : "Copiar"}</span>
    </button>
  );
}

