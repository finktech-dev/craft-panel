  document.addEventListener('DOMContentLoaded', () => {
    // Referencias DOM
    const list = document.querySelector('#schematics-list');
    const count = document.querySelector('#schematic-count');
    const lengthInput = document.querySelector('#viaduct-length');
    const lengthOutput = document.querySelector('#viaduct-length-output');
    const banner = document.querySelector('#status-banner');
    const container = document.querySelector('#three-container');
    const loadingOverlay = document.querySelector('#viewer-loading');
    const loadingText = document.querySelector('#loading-text');
    const hudFilename = document.querySelector('#hud-filename');
    const hudDimensions = document.querySelector('#hud-dimensions');
    const hudBlocks = document.querySelector('#hud-blocks');
    const paletteTags = document.querySelector('#palette-tags');
    const paletteCount = document.querySelector('#palette-count');

    // Botones de control del visor
    const btnIso = document.querySelector('#btn-view-iso');
    const btnTop = document.querySelector('#btn-view-top');
    const btnSide = document.querySelector('#btn-view-side');
    const btnToggleRotate = document.querySelector('#btn-toggle-rotate');
    const btnResetCam = document.querySelector('#btn-reset-cam');
    const rotateText = document.querySelector('#rotate-text');

    lengthInput.addEventListener('input', () => {
      lengthOutput.textContent = lengthInput.value;
    });

    // -------------------------------------------------------------
    // Original block textures (see static/textures/blocks/README.md)
    // -------------------------------------------------------------
    const textureLoader = new THREE.TextureLoader();
    const textureCache = {};
    const materialCache = {};

    const TEXTURE_MAP = {
      'stone_bricks': '/static/textures/blocks/stone_bricks.png',
      'cracked_stone_bricks': '/static/textures/blocks/cracked_stone_bricks.png',
      'mossy_stone_bricks': '/static/textures/blocks/mossy_stone_bricks.png',
      'chiseled_stone_bricks': '/static/textures/blocks/chiseled_stone_bricks.png',
      'deepslate_bricks': '/static/textures/blocks/deepslate_bricks.png',
      'cracked_deepslate_bricks': '/static/textures/blocks/cracked_deepslate_bricks.png',
      'deepslate_tiles': '/static/textures/blocks/deepslate_tiles.png',
      'polished_deepslate': '/static/textures/blocks/polished_deepslate.png',
      'polished_andesite': '/static/textures/blocks/polished_andesite.png',
      'andesite': '/static/textures/blocks/andesite.png',
      'gravel': '/static/textures/blocks/gravel.png',
      'dark_oak_planks': '/static/textures/blocks/dark_oak_planks.png',
      'oak_planks': '/static/textures/blocks/oak_planks.png',
      'spruce_planks': '/static/textures/blocks/spruce_planks.png',
      'lantern': '/static/textures/blocks/lantern.png',
      'iron_bars': '/static/textures/blocks/iron_bars.png',
      'glass': '/static/textures/blocks/glass.png',
      'chain': '/static/textures/blocks/chain.png',
      'track': '/static/textures/blocks/create_track.png',
      'andesite_scaffolding': '/static/textures/blocks/create_andesite_scaffold.png',
      'andesite_casing': '/static/textures/blocks/create_andesite_casing.png'
    };

    const BLOCK_PALETTE_DEFS = {
      'stone_bricks': { color: '#888b8d', name: 'Ladrillos de piedra' },
      'cracked_stone_bricks': { color: '#737677', name: 'Ladrillos agrietados' },
      'mossy_stone_bricks': { color: '#68795c', name: 'Ladrillos musgosos' },
      'chiseled_stone_bricks': { color: '#7c7f81', name: 'Piedra labrada cincelada' },
      'deepslate_bricks': { color: '#3a3b40', name: 'Ladrillos de pizarra profunda' },
      'deepslate_tiles': { color: '#303136', name: 'Baldosas de pizarra' },
      'cracked_deepslate_bricks': { color: '#2b2c30', name: 'Pizarra agrietada' },
      'polished_deepslate': { color: '#45464c', name: 'Pizarra pulida' },
      'polished_andesite': { color: '#898c8c', name: 'Andesita pulida' },
      'andesite_scaffolding': { color: '#61676d', name: 'Andamio de andesita (Create)' },
      'andesite_casing': { color: '#5b6167', name: 'Revestimiento de andesita (Create)' },
      'gravel': { color: '#827d76', name: 'Balasto de grava' },
      'track': { color: '#d97706', name: 'Vías de tren (Create)' },
      'lantern': { color: '#fbbf24', name: 'Farol' },
      'chain': { color: '#374151', name: 'Cadena de hierro' },
      'iron_bars': { color: '#94a3b8', name: 'Barras de hierro' },
      'dark_oak_planks': { color: '#3f2818', name: 'Tablones de roble oscuro' },
      'spruce_planks': { color: '#6b4e2d', name: 'Tablones de abeto' },
      'oak_planks': { color: '#9d7c4c', name: 'Tablones de roble' },
      'glass': { color: '#93c5fd', name: 'Cristal' }
    };

    function resolveBlockInfo(rawId) {
      const clean = String(rawId || '').replace(/^[^:]+:/, '').split('[')[0].toLowerCase();
      for (const [key, val] of Object.entries(BLOCK_PALETTE_DEFS)) {
        if (clean.includes(key)) {
          return { color: val.color, name: val.name, key };
        }
      }
      let hash = 0;
      for (let i = 0; i < clean.length; i++) hash = clean.charCodeAt(i) + ((hash << 5) - hash);
      const c = (hash & 0x00ffffff).toString(16).toUpperCase();
      const hex = '#' + '00000'.substring(0, 6 - c.length) + c;
      const formatted = clean.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      return { color: hex, name: formatted, key: clean };
    }

    function getBlockTexture(cleanKey) {
      if (!textureCache[cleanKey]) {
        let path = null;
        for (const [k, p] of Object.entries(TEXTURE_MAP)) {
          if (cleanKey.includes(k)) {
            path = p;
            break;
          }
        }
        if (!path) return null;
        const tex = textureLoader.load(path);
        tex.magFilter = THREE.NearestFilter;
        tex.minFilter = THREE.NearestFilter;
        tex.generateMipmaps = false;
        textureCache[cleanKey] = tex;
      }
      return textureCache[cleanKey];
    }

    function getBlockMaterial(cleanKey, rawName) {
      if (!materialCache[cleanKey]) {
        const tex = getBlockTexture(cleanKey);
        const info = resolveBlockInfo(rawName);

        const options = {
          roughness: 0.8,
          metalness: 0.1
        };

        if (tex) {
          options.map = tex;
        } else {
          options.color = new THREE.Color(info.color);
        }

        if (cleanKey.includes('glass')) {
          options.transparent = true;
          options.opacity = 0.65;
        } else if (cleanKey.includes('iron_bars') || cleanKey.includes('chain') || cleanKey.includes('scaffolding')) {
          options.transparent = true;
          options.alphaTest = 0.25;
        } else if (cleanKey.includes('lantern')) {
          options.transparent = true;
          options.alphaTest = 0.2;
          options.emissive = new THREE.Color(0xfbbf24);
          options.emissiveIntensity = 0.75;
        }

        materialCache[cleanKey] = new THREE.MeshStandardMaterial(options);
      }
      return materialCache[cleanKey];
    }

    // -------------------------------------------------------------
    // Inicialización del Motor WebGL Three.js
    // -------------------------------------------------------------
    let scene, camera, renderer, controls;
    let currentMesh = null;
    let currentGrid = null;
    let isAutoRotating = false;
    let activeSchematicFilename = null;
    let currentBounds = { width: 1, height: 1, length: 1 };

    function initThree() {
      const width = container.clientWidth || 800;
      const height = container.clientHeight || 450;

      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x1a1918);

      camera = new THREE.PerspectiveCamera(45, width / height, 0.5, 2000);
      camera.position.set(40, 30, 45);

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.outputEncoding = THREE.sRGBEncoding;
      container.appendChild(renderer.domElement);

      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.07;
      controls.maxPolarAngle = Math.PI / 2 + 0.08;
      controls.minDistance = 3;
      controls.maxDistance = 500;

      // Luces direccionales y hemisféricas calibradas para texturas de bloques Minecraft
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
      scene.add(ambientLight);

      const hemiLight = new THREE.HemisphereLight(0xbae6fd, 0x1e293b, 0.45);
      scene.add(hemiLight);

      const sunLight = new THREE.DirectionalLight(0xfffaed, 0.85);
      sunLight.position.set(60, 100, 50);
      scene.add(sunLight);

      const fillLight = new THREE.DirectionalLight(0x94a3b8, 0.35);
      fillLight.position.set(-60, 40, -50);
      scene.add(fillLight);

      // Render Loop
      function animate() {
        requestAnimationFrame(animate);
        if (isAutoRotating && controls) {
          controls.autoRotate = true;
          controls.autoRotateSpeed = 1.6;
        } else if (controls) {
          controls.autoRotate = false;
        }
        controls.update();
        renderer.render(scene, camera);
      }
      animate();

      // Ajuste dinámico al redimensionar
      const resizeObserver = new ResizeObserver(() => {
        if (!container || !renderer || !camera) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      });
      resizeObserver.observe(container);
    }

    // -------------------------------------------------------------
    // Posicionamiento de Cámara
    // -------------------------------------------------------------
    function setCameraPreset(preset) {
      const { width: w, height: h, length: l } = currentBounds;
      const maxDim = Math.max(w, h, l, 15);
      const targetY = h * 0.4;
      controls.target.set(0, targetY, 0);

      if (preset === 'iso') {
        camera.position.set(maxDim * 0.95, maxDim * 0.75, maxDim * 0.95);
      } else if (preset === 'top') {
        camera.position.set(0.01, maxDim * 1.5, 0.01);
      } else if (preset === 'side') {
        camera.position.set(maxDim * 1.25, targetY, 0);
      }
      controls.update();
    }

    btnIso.addEventListener('click', () => setCameraPreset('iso'));
    btnTop.addEventListener('click', () => setCameraPreset('top'));
    btnSide.addEventListener('click', () => setCameraPreset('side'));
    btnResetCam.addEventListener('click', () => setCameraPreset('iso'));

    btnToggleRotate.addEventListener('click', () => {
      isAutoRotating = !isAutoRotating;
      if (isAutoRotating) {
        btnToggleRotate.classList.add('border-emerald-400', 'text-emerald-300');
        btnToggleRotate.setAttribute('aria-pressed', 'true');
        rotateText.textContent = 'Frenar el giro';
      } else {
        btnToggleRotate.classList.remove('border-emerald-400', 'text-emerald-300');
        btnToggleRotate.setAttribute('aria-pressed', 'false');
        rotateText.textContent = 'Girar sola';
      }
    });

    // -------------------------------------------------------------
    // Carga e Instanciación de Voxels desde la API
    // -------------------------------------------------------------
    async function loadSchematicPreview(filename) {
      if (!filename) return;
      activeSchematicFilename = filename;
      highlightActiveFile(filename);

      loadingText.textContent = `Cargando ${filename}…`;
      loadingOverlay.classList.remove('opacity-0', 'pointer-events-none');
      hudFilename.textContent = filename;

      try {
        const data = await Panel.api(`/api/schematics/${encodeURIComponent(filename)}/preview`);
        renderVoxels(data);
      } catch (err) {
        console.error('Error al cargar vista 3D:', err);
        Panel.toast(`No pudimos mostrar ${filename} en 3D: ${err.message}`, 'error');
        loadingOverlay.classList.add('opacity-0', 'pointer-events-none');
      }
    }

    function renderVoxels(data) {
      // 1. Limpiar geometría previa de la escena
      if (currentMesh) {
        scene.remove(currentMesh);
        currentMesh.traverse((child) => {
          if (child.geometry) child.geometry.dispose();
        });
        currentMesh = null;
      }
      if (currentGrid) {
        scene.remove(currentGrid);
        currentGrid.geometry.dispose();
        currentGrid = null;
      }

      const { width: w, height: h, length: l, voxels, palette } = data;
      currentBounds = { width: w, height: h, length: l };

      // Actualizar HUD
      hudDimensions.textContent = `${w} × ${h} × ${l}`;
      hudBlocks.textContent = voxels.length.toLocaleString('es-AR');

      // 2. Construir cuadrícula de apoyo en el suelo
      const maxXZ = Math.max(w, l, 20);
      const gridSize = Math.ceil(maxXZ * 1.35);
      currentGrid = new THREE.GridHelper(gridSize, Math.min(gridSize, 50), 0x4a4844, 0x2a2927);
      currentGrid.position.y = -0.02;
      scene.add(currentGrid);

      // 3. Agrupar voxels por tipo de bloque para aplicar texturas reales
      const count = voxels.length;
      if (count === 0) {
        loadingOverlay.classList.add('opacity-0', 'pointer-events-none');
        paletteTags.innerHTML = '<p class="py-4 text-sm text-zinc-500">Este archivo no tiene bloques.</p>';
        return;
      }

      const voxelsByPalette = {};
      for (let i = 0; i < count; i++) {
        const pid = voxels[i][3];
        if (!voxelsByPalette[pid]) voxelsByPalette[pid] = [];
        voxelsByPalette[pid].push(voxels[i]);
      }

      const containerGroup = new THREE.Group();
      const geometry = new THREE.BoxGeometry(0.98, 0.98, 0.98);
      const dummy = new THREE.Object3D();
      const blockStats = {};

      for (const [pidStr, list] of Object.entries(voxelsByPalette)) {
        const rawName = palette[pidStr] || 'minecraft:air';
        if (rawName === 'minecraft:air' || list.length === 0) continue;

        const info = resolveBlockInfo(rawName);
        const mat = getBlockMaterial(info.key, rawName);
        const instMesh = new THREE.InstancedMesh(geometry, mat, list.length);
        instMesh.instanceMatrix.setUsage(THREE.StaticDrawUsage);

        for (let j = 0; j < list.length; j++) {
          const [vx, vy, vz] = list[j];
          dummy.position.set(
            vx - w / 2 + 0.5,
            vy + 0.5,
            vz - l / 2 + 0.5
          );
          dummy.updateMatrix();
          instMesh.setMatrixAt(j, dummy.matrix);
        }
        instMesh.instanceMatrix.needsUpdate = true;
        containerGroup.add(instMesh);

        blockStats[info.name] = {
          count: list.length,
          color: info.color,
          name: info.name,
          key: info.key
        };
      }

      scene.add(containerGroup);
      currentMesh = containerGroup;

      // 4. Centrar cámara de manera óptima
      setCameraPreset('iso');

      // 5. Renderizar tags de desglose de paleta con vista previa de textura
      renderPaletteTags(blockStats, count);

      // Ocultar pantalla de carga
      window.setTimeout(() => {
        loadingOverlay.classList.add('opacity-0', 'pointer-events-none');
      }, 120);
    }

    function renderPaletteTags(blockStats, totalBlocks) {
      const sorted = Object.values(blockStats).sort((a, b) => b.count - a.count);
      paletteCount.textContent = `${sorted.length} tipo${sorted.length === 1 ? '' : 's'} de bloque`;

      paletteTags.innerHTML = sorted.map(stat => {
        const pct = ((stat.count / totalBlocks) * 100).toFixed(1);
        const tex = TEXTURE_MAP[stat.key];
        const iconHtml = tex
          ? `<img src="${tex}" class="pixel-icon h-4 w-4 shrink-0 rounded-sm" alt="" />`
          : `<span class="h-4 w-4 shrink-0 rounded-sm" style="background-color: ${stat.color};"></span>`;

        return `
          <div class="flex items-center gap-3 border-b border-zinc-800 py-2.5 text-sm">
            ${iconHtml}
            <span class="min-w-0 flex-1 truncate text-zinc-200">${Panel.escapeHtml(stat.name)}</span>
            <span class="shrink-0 text-zinc-500">${stat.count.toLocaleString('es-AR')} · ${pct}%</span>
          </div>
        `;
      }).join('');
    }

    function highlightActiveFile(filename) {
      document.querySelectorAll('.schematic-row').forEach(row => {
        const isCurrent = row.dataset.filename === filename;
        const btn = row.querySelector('.btn-preview-3d');
        if (isCurrent) {
          row.setAttribute('aria-current', 'true');
          if (btn) {
            btn.classList.add('border-emerald-400', 'text-emerald-300');
            btn.textContent = 'En la vista previa';
          }
        } else {
          row.removeAttribute('aria-current');
          if (btn) {
            btn.classList.remove('border-emerald-400', 'text-emerald-300');
            btn.textContent = 'Ver en 3D';
          }
        }
      });
    }

    // -------------------------------------------------------------
    // Listado y Descarga de Esquemas
    // -------------------------------------------------------------
    const renderList = (items) => {
      count.textContent = `${items.length} archivo${items.length === 1 ? '' : 's'}`;
      if (!items.length) {
        list.innerHTML = '<p class="py-12 text-center text-zinc-500">Todavía no creaste ninguna construcción. Probá con una de arriba.</p>';
        return;
      }

      list.innerHTML = items.map((item) => `
        <div class="schematic-row flex flex-col gap-3 border-b border-zinc-800 py-4 sm:flex-row sm:items-center" data-filename="${Panel.escapeHtml(item.filename)}">
          <div class="min-w-0 flex-1">
            <h3 class="truncate font-mono text-sm text-zinc-50">${Panel.escapeHtml(item.filename)}</h3>
            <p class="mt-0.5 text-sm text-zinc-500">${item.size_kb} KB · ${new Date(item.modified_at).toLocaleString('es-AR')}</p>
          </div>
          <div class="flex shrink-0 items-center gap-4">
            <button type="button" data-filename="${Panel.escapeHtml(item.filename)}" class="btn-preview-3d v2-button btn-quiet min-h-9 px-3 py-1 text-sm">Ver en 3D</button>
            <a href="/api/schematics/${encodeURIComponent(item.filename)}/download" class="link text-sm">Descargar</a>
          </div>
        </div>
      `).join('');

      // Asignar listeners a los botones "Ver 3D"
      document.querySelectorAll('.btn-preview-3d').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const fn = e.currentTarget.dataset.filename;
          loadSchematicPreview(fn);
        });
      });

      // Si no hay ninguno cargado todavía, cargar el primero disponible
      if (!activeSchematicFilename && items.length > 0) {
        loadSchematicPreview(items[0].filename);
      } else if (activeSchematicFilename) {
        highlightActiveFile(activeSchematicFilename);
      }
    };

    const loadSchematics = async () => {
      try {
        const items = await Panel.api('/api/schematics');
        renderList(items);
        return items;
      } catch (error) {
        list.innerHTML = `<p class="py-12 text-center text-[#f3a79b]">No pudimos cargar tus archivos. ${Panel.escapeHtml(error.message)}</p>`;
        return [];
      }
    };

    // -------------------------------------------------------------
    // Generación de Nuevos Esquemas
    // -------------------------------------------------------------
    const generate = async (button, path, body, targetFilename) => {
      button.disabled = true;
      const originalLabel = button.textContent;
      button.textContent = 'Creando…';

      try {
        const result = await Panel.api(path, { method: 'POST', body });
        Panel.toast(result.message);
        await loadSchematics();
        banner.src = `/api/server/banner.png?updated=${Date.now()}`;
        if (targetFilename) {
          loadSchematicPreview(targetFilename);
        }
      } catch (error) {
        Panel.toast(error.message, 'error');
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    };

    document.querySelector('#generate-viaduct').addEventListener('click', (event) => {
      generate(
        event.currentTarget,
        '/api/schematics/generate-viaduct',
        { length_blocks: Number(lengthInput.value) },
        'viaducto_medieval.nbt'
      );
    });

    document.querySelector('#generate-station').addEventListener('click', (event) => {
      generate(
        event.currentTarget,
        '/api/schematics/generate-station',
        null,
        'estacion_central.nbt'
      );
    });

    document.querySelector('#copy-banner-markdown').addEventListener('click', async () => {
      const markdown = `![Estado](${window.location.origin}/api/server/banner.png)`;
      try {
        await navigator.clipboard.writeText(markdown);
        Panel.toast('Enlace copiado. Pegalo en Discord o en un foro.');
      } catch {
        Panel.toast('No pudimos copiar el enlace. Probá de nuevo.', 'error');
      }
    });

    // Iniciar Three.js y cargar esquemas
    initThree();
    loadSchematics();
  });
