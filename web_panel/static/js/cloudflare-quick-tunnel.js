(() => {
  document.addEventListener("DOMContentLoaded", () => {
    const startButton = document.querySelector("#start-cloudflare");
    if (!startButton) return;

    const stopButton = document.querySelector("#stop-cloudflare");
    const copyButton = document.querySelector("#copy-cloudflare-url");
    const url = document.querySelector("#cloudflare-url");
    const help = document.querySelector("#cloudflare-help");
    let refreshTimer = null;

    const render = (status) => {
      const active = Boolean(status.is_running);
      const publicUrl = status.public_url || "";

      if (url) url.textContent = publicUrl || "Todavía no generada";
      if (help) help.textContent = status.message || "";
      if (startButton) {
        startButton.disabled = active;
        startButton.textContent = active
          ? publicUrl
            ? "Enlace temporal activo"
            : "Generando enlace…"
          : "Crear enlace temporal";
      }
      if (stopButton) stopButton.classList.toggle("hidden", !active);
      if (copyButton) copyButton.classList.toggle("hidden", !publicUrl);
    };

    const refresh = async ({ quiet = false } = {}) => {
      try {
        render(await Panel.api("/api/cloudflare/status"));
      } catch (error) {
        help.textContent = error.message;
        if (!quiet) Panel.toast(error.message, "error");
      }
    };

    startButton.addEventListener("click", async () => {
      startButton.disabled = true;
      try {
        render(await Panel.api("/api/cloudflare/start", { method: "POST" }));
        Panel.toast("Cloudflare está creando el enlace temporal.");
      } catch (error) {
        Panel.toast(error.message, "error");
      } finally {
        await refresh({ quiet: true });
      }
    });

    stopButton.addEventListener("click", async () => {
      stopButton.disabled = true;
      try {
        render(await Panel.api("/api/cloudflare/stop", { method: "POST" }));
        Panel.toast("Enlace temporal detenido.");
      } catch (error) {
        Panel.toast(error.message, "error");
      } finally {
        stopButton.disabled = false;
      }
    });

    copyButton.addEventListener("click", async () => {
      const publicUrl = url.textContent.trim();
      if (!publicUrl.startsWith("https://")) return;

      try {
        await navigator.clipboard.writeText(publicUrl);
        Panel.toast("Enlace copiado.");
      } catch {
        Panel.toast("No se pudo copiar el enlace.", "error");
      }
    });

    refresh({ quiet: true });
    refreshTimer = window.setInterval(() => refresh({ quiet: true }), 2500);
    window.addEventListener("beforeunload", () => {
      if (refreshTimer) window.clearInterval(refreshTimer);
    });
  });
})();
