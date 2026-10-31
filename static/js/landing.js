/**
 * FloorPlan3D — Editorial Studio Landing Page Controller
 * Handles:
 * 1. Parallax bracketing on hero wordmarks and cut-out subject
 * 2. Staggered scroll reveals respecting prefers-reduced-motion
 * 3. Real-to-scale SVG plan rendering with shoelace area formula
 * 4. Pinned orbit study with stated mathematical model and live readouts
 * 5. Dynamic work table population from samples/index.json
 * 6. Seamless view switching between landing studio and 3D app view
 */

(function () {
  'use strict';

  // Sample scene geometric fallback data in case network fetch is delayed
  const FALLBACK_SCENE = {
    meta: { metersPerPixel: 0.02, wallHeight: 3.0, wallThickness: 0.2 },
    rooms: [
      { id: 'r1', type: 'classroom', label: 'Classroom 101', polygon: [[1.12, 1.12], [7.28, 1.12], [7.28, 5.88], [1.12, 5.88]] },
      { id: 'r2', type: 'lab', label: 'Computer Lab', polygon: [[7.52, 1.12], [14.88, 1.12], [14.88, 5.88], [7.52, 5.88]] },
      { id: 'r3', type: 'corridor', label: 'Main Corridor', polygon: [[1.12, 6.0], [14.88, 6.0], [14.88, 7.2], [10.2, 7.2], [10.2, 10.88], [14.88, 10.88], [14.88, 11.0], [10.0, 11.0], [10.0, 7.2], [1.12, 7.2]] },
      { id: 'r4', type: 'restroom', label: 'Restroom', polygon: [[1.12, 7.32], [5.28, 7.32], [5.28, 10.88], [1.12, 10.88]] },
      { id: 'r5', type: 'room', label: 'Faculty Office', polygon: [[5.52, 7.32], [9.98, 7.32], [9.98, 10.88], [5.52, 10.88]] },
      { id: 'r6', type: 'entrance', label: 'East Lobby', polygon: [[10.32, 7.32], [12.38, 7.32], [12.38, 10.88], [10.32, 10.88]] },
      { id: 'r7', type: 'stairs', label: 'Stairwell', polygon: [[12.62, 7.32], [14.78, 7.32], [14.78, 10.88], [12.62, 10.88]] }
    ],
    walls: [
      { id: 'north', polygon: [[1.0, 1.0], [15.0, 1.0], [15.0, 1.2], [1.0, 1.2]] },
      { id: 'west', polygon: [[1.0, 1.0], [1.2, 1.0], [1.2, 11.0], [1.0, 11.0]] },
      { id: 'east', polygon: [[14.8, 1.0], [15.0, 1.0], [15.0, 11.0], [14.8, 11.0]] },
      { id: 'south', polygon: [[1.0, 10.8], [15.0, 10.8], [15.0, 11.0], [1.0, 11.0]] },
      { id: 'div_upper', polygon: [[1.0, 5.9], [15.0, 5.9], [15.0, 6.1], [1.0, 6.1]] },
      { id: 'div_mid', polygon: [[7.3, 1.0], [7.5, 1.0], [7.5, 6.0], [7.3, 6.0]] },
      { id: 'div_lower', polygon: [[1.0, 7.1], [12.4, 7.1], [12.4, 7.3], [1.0, 7.3]] }
    ],
    doors: [
      { id: 'd1', center: [4.0, 6.0], width: 0.72 },
      { id: 'd2', center: [11.0, 6.0], width: 0.72 },
      { id: 'd3', center: [3.2, 7.2], width: 0.64 },
      { id: 'd4', center: [7.8, 7.2], width: 0.68 },
      { id: 'd5', center: [1.1, 6.16], width: 0.88 },
      { id: 'd8', center: [11.35, 10.9], width: 1.0 }
    ]
  };

  // Helper: Shoelace formula for polygonal area in square meters
  function computePolygonArea(vertices) {
    if (!vertices || vertices.length < 3) return 0;
    let area = 0;
    const n = vertices.length;
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      area += vertices[i][0] * vertices[j][1];
      area -= vertices[j][0] * vertices[i][1];
    }
    return Math.abs(area) / 2.0;
  }

  // Helper: Compute polygon center
  function computePolygonCenter(vertices) {
    let sx = 0, sy = 0;
    for (const v of vertices) {
      sx += v[0];
      sy += v[1];
    }
    return [sx / vertices.length, sy / vertices.length];
  }

  /* -------------------------------------------------------------------------
   * 1. Hero Parallax & Bracketing Animation
   * ------------------------------------------------------------------------- */
  function initHeroParallax() {
    const heroSec = document.querySelector('.studio-hero');
    const upperWordmark = document.querySelector('.hero-wordmark-upper');
    const lowerWordmark = document.querySelector('.hero-wordmark-lower');
    const subjectWrapper = document.querySelector('.hero-subject-wrapper');

    if (!heroSec || !upperWordmark || !lowerWordmark || !subjectWrapper) return;

    // Immediately reveal hero elements on requestAnimationFrame (per spec, not observed)
    requestAnimationFrame(() => {
      upperWordmark.style.opacity = '1';
      lowerWordmark.style.opacity = '1';
      subjectWrapper.style.opacity = '1';
      const copyStack = document.querySelector('.hero-copy-stack');
      if (copyStack) copyStack.style.opacity = '1';
      const caption = document.querySelector('.hero-corner-caption');
      if (caption) caption.style.opacity = '1';
    });

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    function onScroll() {
      const scrollY = window.pageYOffset || document.documentElement.scrollTop;
      const heroHeight = heroSec.offsetHeight;
      if (scrollY > heroHeight * 1.5) return; // Skip calculation when scrolled past

      const progress = Math.min(Math.max(scrollY / heroHeight, 0), 1);
      const vh = window.innerHeight;
      const vw = window.innerWidth;

      // Upper line moves UP and OUTWARD about 20vh
      const upperDistY = -progress * (vh * 0.20);
      const upperDistX = progress * (vw * 0.04);
      upperWordmark.style.transform = `translate3d(${upperDistX.toFixed(1)}px, ${upperDistY.toFixed(1)}px, 0)`;

      // Lower line moves DOWN and OUTWARD about 20vh
      const lowerDistY = progress * (vh * 0.20);
      const lowerDistX = progress * (vw * 0.045);
      lowerWordmark.style.transform = `translate3d(${lowerDistX.toFixed(1)}px, ${lowerDistY.toFixed(1)}px, 0)`;

      // Subject rises roughly 24vh and scales up slightly
      const subjectRiseY = -progress * (vh * 0.24);
      const subjectScale = 1.0 + (progress * 0.08);
      subjectWrapper.style.transform = `translate3d(0, calc(-50% + ${subjectRiseY.toFixed(1)}px), 0) scale(${subjectScale.toFixed(3)})`;
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    onScroll();
  }

  /* -------------------------------------------------------------------------
   * 2. Staggered Scroll Reveal
   * ------------------------------------------------------------------------- */
  function initScrollReveal() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const nodes = document.querySelectorAll('.reveal-node');
    if (!nodes.length) return;

    const observer = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const el = entry.target;
          const delay = parseInt(el.getAttribute('data-reveal-delay') || '0', 10);
          setTimeout(() => {
            el.classList.add('is-revealed');
          }, delay);
          obs.unobserve(el);
        }
      });
    }, { rootMargin: '0px 0px -40px 0px', threshold: 0.05 });

    nodes.forEach((node, idx) => {
      // 0.07s steps between siblings
      const stagger = (idx % 6) * 70;
      node.setAttribute('data-reveal-delay', stagger.toString());
      observer.observe(node);
    });
  }

  /* -------------------------------------------------------------------------
   * 3. Section Drawing: SVG Line Drawing strictly TO SCALE in real meters
   * ------------------------------------------------------------------------- */
  function renderScaleDrawing(scene) {
    const container = document.getElementById('drawing-svg-mount');
    if (!container) return;

    const rooms = scene.rooms || [];
    const walls = scene.walls || [];
    const doors = scene.doors || [];

    // Bounding box in real meters
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    rooms.forEach(r => {
      (r.polygon || []).forEach(([x, y]) => {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      });
    });

    if (!isFinite(minX)) {
      minX = 0; minY = 0; maxX = 16; maxY = 12;
    }

    const pad = 1.5;
    const viewMinX = minX - pad;
    const viewMinY = minY - pad;
    const viewW = (maxX - minX) + pad * 2;
    const viewH = (maxY - minY) + pad * 2;

    const svgParts = [
      `<svg viewBox="${viewMinX.toFixed(2)} ${viewMinY.toFixed(2)} ${viewW.toFixed(2)} ${viewH.toFixed(2)}" xmlns="http://www.w3.org/2000/svg" style="background-color: var(--ground);">`,
      `<defs>`,
      `  <pattern id="planGrid" width="1" height="1" patternUnits="userSpaceOnUse">`,
      `    <path d="M 1 0 L 0 0 0 1" fill="none" stroke="rgba(26,25,23,0.07)" stroke-width="0.04" />`,
      `  </pattern>`,
      `</defs>`,
      `<rect x="${viewMinX.toFixed(2)}" y="${viewMinY.toFixed(2)}" width="${viewW.toFixed(2)}" height="${viewH.toFixed(2)}" fill="url(#planGrid)" />`
    ];

    // Hairline construction geometry & grid lines
    svgParts.push(`<g class="construction-lines" stroke="rgba(26,25,23,0.12)" stroke-width="0.03" stroke-dasharray="0.2, 0.2">`);
    svgParts.push(`  <line x1="${minX}" y1="${viewMinY}" x2="${minX}" y2="${viewMinY + viewH}" />`);
    svgParts.push(`  <line x1="${maxX}" y1="${viewMinY}" x2="${maxX}" y2="${viewMinY + viewH}" />`);
    svgParts.push(`  <line x1="${viewMinX}" y1="${minY}" x2="${viewMinX + viewW}" y2="${minY}" />`);
    svgParts.push(`  <line x1="${viewMinX}" y1="${maxY}" x2="${viewMinX + viewW}" y2="${maxY}" />`);
    svgParts.push(`</g>`);

    // Room boundaries & shoelace calculated areas
    svgParts.push(`<g class="rooms-layer">`);
    rooms.forEach(r => {
      const pts = (r.polygon || []).map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
      const area = computePolygonArea(r.polygon);
      const [cx, cy] = computePolygonCenter(r.polygon);

      svgParts.push(`  <polygon points="${pts}" fill="rgba(26,25,23,0.02)" stroke="rgba(26,25,23,0.25)" stroke-width="0.04" />`);

      // Thin leader line from room center out to mono label
      const leaderTargetX = cx;
      const leaderTargetY = cy - 0.45;
      svgParts.push(`  <line x1="${cx.toFixed(2)}" y1="${cy.toFixed(2)}" x2="${leaderTargetX.toFixed(2)}" y2="${leaderTargetY.toFixed(2)}" stroke="rgba(26,25,23,0.35)" stroke-width="0.02" />`);
      svgParts.push(`  <circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="0.06" fill="#9B3418" />`);

      // Room name & area label in Azeret Mono
      svgParts.push(`  <text x="${cx.toFixed(2)}" y="${(cy + 0.15).toFixed(2)}" font-family="'Azeret Mono', monospace" font-size="0.32" font-weight="600" fill="#1A1917" text-anchor="middle" letter-spacing="0.02em">${escapeXml(r.label || r.id)}</text>`);
      svgParts.push(`  <text x="${cx.toFixed(2)}" y="${(cy + 0.52).toFixed(2)}" font-family="'Azeret Mono', monospace" font-size="0.25" font-weight="400" fill="#6E6A61" text-anchor="middle">${area.toFixed(1)} m²</text>`);
    });
    svgParts.push(`</g>`);

    // Walls with HEAVIER stroke so they do not read as leaders
    svgParts.push(`<g class="walls-layer">`);
    walls.forEach(w => {
      const pts = (w.polygon || []).map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
      svgParts.push(`  <polygon points="${pts}" fill="#1A1917" stroke="#1A1917" stroke-width="0.08" stroke-linejoin="miter" />`);
    });
    svgParts.push(`</g>`);

    // Doors with swing arcs & pigment markers
    svgParts.push(`<g class="doors-layer">`);
    doors.forEach(d => {
      const [dx, dy] = d.center || [0, 0];
      const dw = d.width || 0.9;
      // Pigment marker
      svgParts.push(`  <circle cx="${dx.toFixed(2)}" cy="${dy.toFixed(2)}" r="0.12" fill="#9B3418" />`);
      // Door swing arc
      const arcR = dw;
      svgParts.push(`  <path d="M ${dx.toFixed(2)} ${dy.toFixed(2)} A ${arcR} ${arcR} 0 0 1 ${(dx + arcR * 0.7).toFixed(2)} ${(dy - arcR * 0.7).toFixed(2)}" fill="none" stroke="#9B3418" stroke-width="0.035" stroke-dasharray="0.1, 0.08" />`);
    });
    svgParts.push(`</g>`);

    // 1m, 2m, 5m Graphic Scale Bar
    const barX = minX;
    const barY = maxY + 0.8;
    svgParts.push(`<g class="scale-bar" font-family="'Azeret Mono', monospace" font-size="0.22" fill="#6E6A61">`);
    svgParts.push(`  <line x1="${barX}" y1="${barY}" x2="${barX + 5}" y2="${barY}" stroke="#1A1917" stroke-width="0.06" />`);
    svgParts.push(`  <line x1="${barX}" y1="${barY - 0.15}" x2="${barX}" y2="${barY + 0.15}" stroke="#1A1917" stroke-width="0.06" />`);
    svgParts.push(`  <line x1="${barX + 1}" y1="${barY - 0.1}" x2="${barX + 1}" y2="${barY + 0.1}" stroke="#1A1917" stroke-width="0.04" />`);
    svgParts.push(`  <line x1="${barX + 2}" y1="${barY - 0.1}" x2="${barX + 2}" y2="${barY + 0.1}" stroke="#1A1917" stroke-width="0.04" />`);
    svgParts.push(`  <line x1="${barX + 5}" y1="${barY - 0.15}" x2="${barX + 5}" y2="${barY + 0.15}" stroke="#1A1917" stroke-width="0.06" />`);
    svgParts.push(`  <text x="${barX}" y="${barY - 0.22}" text-anchor="middle">0m</text>`);
    svgParts.push(`  <text x="${barX + 1}" y="${barY - 0.22}" text-anchor="middle">1m</text>`);
    svgParts.push(`  <text x="${barX + 2}" y="${barY - 0.22}" text-anchor="middle">2m</text>`);
    svgParts.push(`  <text x="${barX + 5}" y="${barY - 0.22}" text-anchor="middle">5m</text>`);
    svgParts.push(`  <text x="${barX + 2.5}" y="${barY + 0.4}" text-anchor="middle" font-size="0.2" letter-spacing="0.1em" fill="#1A1917">SCALE 1:50 METRIC</text>`);
    svgParts.push(`</g>`);

    svgParts.push(`</svg>`);
    container.innerHTML = svgParts.join('\n');
  }

  function escapeXml(str) {
    return String(str).replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
  }

  /* -------------------------------------------------------------------------
   * 4. Pinned Study: Camera Orbit Driven by Stated Mathematical Model
   * ------------------------------------------------------------------------- */
  function initOrbitStudy(scene) {
    const studyWrapper = document.getElementById('study-section');
    const markerDot = document.getElementById('study-camera-marker');
    const orbitRay = document.getElementById('study-orbit-ray');
    const readoutProgress = document.getElementById('readout-progress');
    const readoutAzimuth = document.getElementById('readout-azimuth');
    const readoutRadius = document.getElementById('readout-radius');
    const readoutCoords = document.getElementById('readout-coords');

    if (!studyWrapper || !markerDot) return;

    // Plan geometry dimensions in meters
    const rooms = scene.rooms || FALLBACK_SCENE.rooms;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    rooms.forEach(r => {
      (r.polygon || []).forEach(([x, y]) => {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      });
    });

    const cx = (minX + maxX) / 2;
    const cz = (minY + maxY) / 2;
    const planWidth = maxX - minX;
    const planHeight = maxY - minY;
    const planDiag = Math.hypot(planWidth, planHeight);
    
    // Model definition:
    // Orbit radius R = 1.6 x diagonal
    // Azimuth θ = scrollProgress x 270°
    const orbitRadius = 1.6 * planDiag;

    function updateStudy() {
      const rect = studyWrapper.getBoundingClientRect();
      const windowH = window.innerHeight;
      const totalScrollable = rect.height - windowH;

      let progress = 0;
      if (rect.top <= 0) {
        progress = Math.min(Math.max(-rect.top / totalScrollable, 0), 1);
      }

      const azimuthDeg = progress * 270;
      const azimuthRad = (azimuthDeg * Math.PI) / 180;

      // Camera coordinates in meters according to stated model
      const camX = cx + orbitRadius * Math.cos(azimuthRad);
      const camZ = cz + orbitRadius * Math.sin(azimuthRad);

      // SVG stage coordinates (percentage based per spec)
      // Center of stage is (50%, 50%)
      const stageRadiusPercent = 38; // container percentage
      const markerPercentX = 50 + stageRadiusPercent * Math.cos(azimuthRad);
      const markerPercentY = 50 + stageRadiusPercent * Math.sin(azimuthRad);

      markerDot.setAttribute('cx', `${markerPercentX.toFixed(2)}%`);
      markerDot.setAttribute('cy', `${markerPercentY.toFixed(2)}%`);

      if (orbitRay) {
        orbitRay.setAttribute('x1', '50%');
        orbitRay.setAttribute('y1', '50%');
        orbitRay.setAttribute('x2', `${markerPercentX.toFixed(2)}%`);
        orbitRay.setAttribute('y2', `${markerPercentY.toFixed(2)}%`);
      }

      // Update readouts
      if (readoutProgress) readoutProgress.textContent = `${Math.round(progress * 100)}%`;
      if (readoutAzimuth) readoutAzimuth.textContent = `${azimuthDeg.toFixed(1)}°`;
      if (readoutRadius) readoutRadius.textContent = `${orbitRadius.toFixed(2)} m`;
      if (readoutCoords) readoutCoords.textContent = `(${camX.toFixed(2)}, ${camZ.toFixed(2)}) m`;
    }

    window.addEventListener('scroll', updateStudy, { passive: true });
    updateStudy();
  }

  /* -------------------------------------------------------------------------
   * 5. Table of Work ("Plans processed"): Loaded from samples/index.json
   * ------------------------------------------------------------------------- */
  function populateWorkTable() {
    const tableBody = document.getElementById('work-table-body');
    if (!tableBody) return;

    // Fetch index.json (try static data mirror then samples/index.json)
    fetch('/static/data/index.json')
      .then(res => res.json())
      .catch(() => fetch('/samples/index.json').then(r => r.json()))
      .catch(() => [
        {
          id: 'sample-academic',
          name: 'Academic Wing Floor 1',
          rooms: 7,
          doors: 8,
          windows: 5,
          scale: '0.020 m/px',
          method: 'SAM 3.1',
          classification: 'Educational Facility'
        },
        {
          id: 'sample-two-story',
          name: 'Academic Complex (2-Story)',
          rooms: 14,
          doors: 16,
          windows: 10,
          scale: '0.020 m/px',
          method: 'SAM 3.1',
          classification: 'Multi-Story Institutional'
        },
        {
          id: 'sample-opencv-suite',
          name: 'Studio Annex & Restrooms',
          rooms: 7,
          doors: 8,
          windows: 5,
          scale: '0.020 m/px',
          method: 'OpenCV',
          classification: 'Commercial Office'
        }
      ])
      .then(entries => {
        tableBody.innerHTML = '';
        entries.forEach((item, idx) => {
          const tr = document.createElement('tr');
          tr.className = 'clickable-row reveal-node';
          tr.setAttribute('data-reveal-delay', (idx * 60).toString());

          tr.innerHTML = `
            <td>
              <div class="project-name">${escapeXml(item.name)}</div>
              <div class="project-meta mono-caption" style="margin-top:2px;">${escapeXml(item.classification || 'Architectural Floor Plan')}</div>
            </td>
            <td class="mono-label" style="color:var(--ink);">${item.rooms}</td>
            <td class="mono-label" style="color:var(--ink);">${item.doors}</td>
            <td class="mono-caption">${escapeXml(item.scale || '0.020 m/px')}</td>
            <td class="mono-label" style="color:var(--pigment);">${escapeXml(item.method || 'SAM 3.1')}</td>
            <td style="text-align:right;">
              <span class="table-action-pill">Load in 3D →</span>
            </td>
          `;

          tr.addEventListener('click', () => {
            switchToAppView();
            if (item.id === 'sample-two-story') {
              const btnTwo = document.getElementById('btn-load-two-story-demo');
              if (btnTwo) btnTwo.click();
            } else {
              const btnOne = document.getElementById('btn-load-demo');
              if (btnOne) btnOne.click();
            }
          });

          tableBody.appendChild(tr);
        });
      });
  }

  /* -------------------------------------------------------------------------
   * 6. View Switching: Landing Studio <-> 3D Application View
   * ------------------------------------------------------------------------- */
  function switchToAppView() {
    const landingView = document.getElementById('landing-view');
    const appView = document.getElementById('app-view');
    if (!landingView || !appView) return;

    landingView.classList.add('view-hidden');
    appView.classList.remove('view-hidden');

    window.scrollTo({ top: 0, behavior: 'instant' });

    // Trigger window resize so Three.js canvas sizes properly
    setTimeout(() => {
      window.dispatchEvent(new Event('resize'));
    }, 50);
  }

  function switchToLandingView() {
    const landingView = document.getElementById('landing-view');
    const appView = document.getElementById('app-view');
    if (!landingView || !appView) return;

    appView.classList.add('view-hidden');
    landingView.classList.remove('view-hidden');

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function initViewSwitching() {
    // Buttons that open App View
    document.querySelectorAll('[data-action="open-app-upload"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        switchToAppView();
        const dropZone = document.getElementById('drop-zone');
        if (dropZone) {
          dropZone.scrollIntoView({ behavior: 'smooth' });
        }
      });
    });

    document.querySelectorAll('[data-action="open-app-sample"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        switchToAppView();
        const btnDemo = document.getElementById('btn-load-demo');
        if (btnDemo) btnDemo.click();
      });
    });

    // "Back to Studio" links inside App View
    document.querySelectorAll('[data-action="back-to-landing"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        switchToLandingView();
      });
    });

    // Expose switch methods globally if needed
    window.FloorPlan3DStudio = {
      switchToAppView,
      switchToLandingView
    };
  }

  /* -------------------------------------------------------------------------
   * Bootstrap
   * ------------------------------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', () => {
    initHeroParallax();
    initScrollReveal();
    initViewSwitching();
    populateWorkTable();

    // Fetch scene data for scale drawing and study
    fetch('/api/sample')
      .then(res => res.json())
      .then(data => {
        const scene = (data && data.scene) ? data.scene : FALLBACK_SCENE;
        renderScaleDrawing(scene);
        initOrbitStudy(scene);
      })
      .catch(() => {
        renderScaleDrawing(FALLBACK_SCENE);
        initOrbitStudy(FALLBACK_SCENE);
      });
  });

})();
