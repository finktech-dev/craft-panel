"use client";

import { useState, useEffect, useCallback } from "react";
import { CopyAddressButton } from "./copy-address-button";

interface McPlayer {
  uuid?: string;
  name_clean: string;
}

interface McStatusResponse {
  online: boolean;
  players?: {
    online: number;
    max: number;
    list?: McPlayer[];
  };
  motd?: {
    clean?: string;
  };
  version?: {
    name_clean?: string;
  };
  icon?: string;
}

interface ServerLiveStatusProps {
  address: string;
}

export function ServerLiveStatus({ address }: ServerLiveStatusProps) {
  const [status, setStatus] = useState<McStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const fetchStatus = useCallback(async (isManual = false) => {
    if (isManual) setIsRefreshing(true);
    try {
      // Intencionalmente desde el navegador: Vercel no tiene conectividad con la PC anfitriona.
      const res = await fetch(`https://api.mcstatus.io/v2/status/java/${encodeURIComponent(address)}`, {
        headers: { "Accept": "application/json" }
      });
      if (res.ok) {
        const data: McStatusResponse = await res.json();
        setStatus(data);
      } else {
        setStatus({ online: false });
      }
    } catch {
      setStatus({ online: false });
    } finally {
      setIsLoading(false);
      if (isManual) {
        setTimeout(() => setIsRefreshing(false), 600);
      }
      setLastChecked(new Date());
    }
  }, [address]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void fetchStatus();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [fetchStatus]);

  const isOnline = status?.online ?? false;
  const playersOnline = status?.players?.online ?? 0;
  const maxPlayers = status?.players?.max ?? 20;
  const playerList = status?.players?.list ?? [];
  const motd = status?.motd?.clean?.trim();
  const serverIcon = status?.icon;

  return (
    <div className={`live-server-card ${isOnline ? "is-online" : "is-offline"}`}>
      {/* Header Row: Status Indicator & Refresh */}
      <div className="live-status-header">
        <div className="status-indicator-group">
          <span className={`status-pulse-dot ${isLoading ? "is-loading" : isOnline ? "is-online" : "is-offline"}`} />
          <div className="status-title-wrap">
            <span className="status-badge-text">
              {isLoading
                ? "COMPROBANDO ESTADO..."
                : isOnline
                ? `EN LÍNEA · ${playersOnline}/${maxPlayers} JUGADORES`
                : "SERVIDOR DESCONECTADO"}
            </span>
          </div>
        </div>

        <button
          type="button"
          className={`status-refresh-btn ${isRefreshing ? "is-spinning" : ""}`}
          onClick={() => fetchStatus(true)}
          disabled={isRefreshing || isLoading}
          title="Comprobar estado en tiempo real"
          aria-label="Comprobar estado en tiempo real"
        >
          <span className="refresh-icon">🔄</span>
          <span className="refresh-label">{isRefreshing ? "Comprobando..." : "Actualizar"}</span>
        </button>
      </div>

      {/* When online: Show MOTD and active players */}
      {isOnline && (
        <div className="live-details-box">
          {serverIcon && (
            <img
              src={serverIcon}
              alt="Icono del servidor"
              className="live-server-icon"
              width={36}
              height={36}
            />
          )}
          <div className="live-details-content">
            {motd && <p className="live-motd-text">{motd}</p>}
            
            {playersOnline > 0 && playerList.length > 0 ? (
              <div className="live-players-section">
                <span className="players-label">Jugando ahora:</span>
                <div className="player-avatars-row">
                  {playerList.slice(0, 10).map((p) => (
                    <div
                      key={p.name_clean}
                      className="player-avatar-chip"
                      title={p.name_clean}
                    >
                      <img
                        src={`https://mc-heads.net/avatar/${encodeURIComponent(p.name_clean)}/22`}
                        alt={p.name_clean}
                        className="player-head-img"
                        width={22}
                        height={22}
                        loading="lazy"
                      />
                      <span className="player-chip-name">{p.name_clean}</span>
                    </div>
                  ))}
                  {playersOnline > 10 && (
                    <span className="players-more-badge">+{playersOnline - 10} más</span>
                  )}
                </div>
              </div>
            ) : (
              <p className="live-empty-notice">El servidor está libre. ¡Sé el primero en entrar a jugar!</p>
            )}
          </div>
        </div>
      )}

      {/* When offline: Friendly helper text */}
      {!isLoading && !isOnline && (
        <p className="live-offline-note">
          La PC anfitriona está apagada o el servidor no se ha iniciado. Podés copiar la dirección IP o descargar el modpack mientras tanto.
        </p>
      )}

      {/* Connection Address & Copy Section */}
      <div className="live-address-section">
        <span className="address-label">DIRECCIÓN DE CONEXIÓN</span>
        <div className="address-inline">
          <code>{address}</code>
          <CopyAddressButton address={address} />
        </div>
      </div>

      {lastChecked && (
        <div className="live-card-footer">
          <small>
            Última comprobación: {lastChecked.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </small>
          <small>Estado público consultado mediante mcstatus.io; no expone el panel ni credenciales.</small>
        </div>
      )}
    </div>
  );
}
