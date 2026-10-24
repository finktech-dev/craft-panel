document.addEventListener('DOMContentLoaded', () => {
  const list = document.querySelector('#backups-list');
  const empty = document.querySelector('#backups-empty');
  const dialog = document.querySelector('#restore-dialog');
  const restoreName = document.querySelector('#restore-filename');
  const escape = Panel.escapeHtml;
  let selectedBackup = null;

  // Show dates the way people say them; fall back to the raw value if it does not parse.
  const formatDate = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('es-AR', { dateStyle: 'long', timeStyle: 'short' });
  };

  const loadBackups = async () => {
    try {
      const backups = await Panel.api('/api/backups');
      list.replaceChildren();
      if (!backups.length) {
        list.classList.add('hidden');
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      list.classList.remove('hidden');
      backups.forEach((backup) => {
        const file = encodeURIComponent(backup.filename);
        const row = document.createElement('article');
        row.className = 'flex flex-col gap-3 border-b border-zinc-800 py-4 sm:flex-row sm:items-center sm:justify-between';
        row.innerHTML = `
          <div class="min-w-0">
            <h3 class="font-semibold text-zinc-50">${escape(formatDate(backup.created_at))}</h3>
            <p class="mt-0.5 truncate text-sm text-zinc-500">${escape(backup.size_mb.toFixed(1))} MB · <span class="font-mono text-xs">${escape(backup.filename)}</span></p>
          </div>
          <div class="flex shrink-0 flex-wrap items-center gap-2">
            <button type="button" class="restore-backup v2-button btn-quiet" data-file="${file}">Volver a esta copia</button>
            <a class="rounded-lg px-2 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100" href="/api/backups/${file}/download">Descargar</a>
            <button type="button" class="delete-backup rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-[#f3a79b]" data-file="${file}">Borrar</button>
          </div>`;
        list.append(row);
      });
    } catch (issue) {
      empty.classList.add('hidden');
      list.classList.remove('hidden');
      list.innerHTML = `<p class="py-6 text-[#f3a79b]">No pudimos leer las copias. ${escape(issue.message)}</p>`;
      Panel.toast(issue.message, 'error');
    }
  };

  const loadCrash = async () => {
    const target = document.querySelector('#crash-report');
    try {
      const report = await Panel.api('/api/server/crash-report');
      target.innerHTML = `
        <p class="font-semibold text-zinc-50">${escape(report.cause)}</p>
        <p class="mt-1 leading-relaxed text-zinc-400">${escape(report.suggestion)}</p>
        <p class="mt-3 text-sm text-zinc-500">Mod que pudo causarlo: ${escape(report.suspected_mod || 'no sabemos')} · <span class="font-mono text-xs">${escape(report.filename)}</span></p>`;
    } catch (issue) {
      target.innerHTML = issue.status === 404
        ? '<p class="text-zinc-400">No hubo cierres inesperados.</p>'
        : `<p class="text-[#f3a79b]">No pudimos revisar. ${escape(issue.message)}</p>`;
    }
  };

  document.querySelector('#flush-save')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await Panel.sendConsoleCommand('save-all flush');
      Panel.toast('Listo, el mundo quedó guardado en el disco.', 'success');
    } catch (issue) {
      Panel.toast(issue.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector('#audit-backups')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    if (!window.confirm('Vamos a revisar todas las copias. Se borran las más viejas que pasen el límite; las dañadas no se tocan. ¿Seguimos?')) return;
    button.disabled = true;
    try {
      const result = await Panel.api('/api/backups/audit', { method: 'POST' });
      const corrupt = result.skipped_corrupt.length;
      Panel.toast(`Listo: ${result.checked.length} revisadas, ${result.deleted.length} borradas${corrupt ? `, ${corrupt} dañada(s) que no se tocaron` : ''}.`, corrupt ? 'error' : 'success');
      await loadBackups();
    } catch (issue) {
      Panel.toast(issue.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  // Copies and restores run as jobs: their progress stays visible where they started,
  // also after a reload, and a failure keeps its message and what to do next.
  const finishJob = async (job, mount) => {
    if (!job) return;
    if (job.status === 'succeeded') {
      Panel.toast(job.message, 'success');
      window.setTimeout(() => {
        const node = document.querySelector(mount);
        if (node?.dataset.jobId === job.id) node.classList.add('hidden');
      }, 8000);
    } else {
      Panel.toast(job.error || job.message, 'error');
    }
    await loadBackups();
  };

  document.querySelector('#create-backup').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    try {
      await finishJob(await PanelJobs.start('/api/backups', { mount: '#backup-progress', button }), '#backup-progress');
    } catch (issue) {
      Panel.toast(issue.message, 'error');
    }
  });

  list.addEventListener('click', async (event) => {
    const restore = event.target.closest('.restore-backup');
    const remove = event.target.closest('.delete-backup');
    if (restore) {
      selectedBackup = decodeURIComponent(restore.dataset.file);
      restoreName.textContent = selectedBackup;
      dialog.showModal();
    }
    if (remove) {
      const filename = decodeURIComponent(remove.dataset.file);
      if (!window.confirm(`¿Borrar la copia ${filename}? No se puede deshacer.`)) return;
      try {
        await Panel.api(`/api/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        Panel.toast('Copia borrada.', 'success');
        await loadBackups();
      } catch (issue) {
        Panel.toast(issue.message, 'error');
      }
    }
  });

  document.querySelector('#confirm-restore').addEventListener('click', async (event) => {
    event.preventDefault();
    if (!selectedBackup) return;
    const button = event.currentTarget;
    button.disabled = true;
    try {
      // The dialog closes as soon as the job exists; progress continues on the page.
      const job = await PanelJobs.start(`/api/backups/${encodeURIComponent(selectedBackup)}/restore`, {
        mount: '#restore-progress',
        onAccepted: () => dialog.close(),
      });
      await finishJob(job, '#restore-progress');
    } catch (issue) {
      Panel.toast(issue.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector('#refresh-crash').addEventListener('click', loadCrash);
  PanelJobs.resume({ kinds: ['backup'], mount: '#backup-progress', button: '#create-backup' }).then((job) => finishJob(job, '#backup-progress'));
  PanelJobs.resume({ kinds: ['restore'], mount: '#restore-progress' }).then((job) => finishJob(job, '#restore-progress'));
  loadBackups();
  loadCrash();
});
