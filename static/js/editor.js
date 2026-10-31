/**
 * FloorPlan3D — 2D Floor Plan Editor
 * Strict Editorial Studio Architecture & Native SVG Vector Canvas
 *
 * Constant Screen-Size Label & Adaptive Metric Grid Engine:
 * 1. Labels rendered in screen-space overlay layer (1:1 pixels, never scaling with zoom).
 *    Screen sizes: ruler 10px, wall/dimension length 11px, room labels 12px, text objects >= 8px.
 *    paint-order: stroke fill with 3px bone (#E7E3DA) halo for total readability over lines.
 * 2. vector-effect: non-scaling-stroke on all hairlines, grid lines, outlines, selection boxes.
 *    Handles and snap markers fixed 8px squares in screen space.
 * 3. Adaptive ruler & grid: label steps from [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100] m
 *    guaranteeing at least 80px spacing and <= 15 labels per axis. Rulers along top & left edges.
 *    Minor grid lines (0.25m) fade out when < 6px; 1m lines shown when >= 10px; 5m lines always.
 * 4. Live wall label: horizontal 11px bone badge with hairline border, offset 12px from line.
 *    Angle in degrees displayed when Shift is held.
 * 5. Default view: 50 px/m centered on 12m x 8m area.
 *    Under 20 px/m, fine details (door arcs, furniture inner lines) automatically simplify.
 */

(function () {
  'use strict';

  // Room floor tint palette conforming to Editorial Studio standard
  const ROOM_COLORS = {
    classroom: '#CBD0C4',
    lab: '#D6C2B4',
    corridor: '#E7E3DA',
    restroom: '#C3CCCB',
    stairs: '#BDB6A6',
    entrance: '#D9CDB0',
    library: '#CFC4B0',
    room: '#D9D4C7',
    elevator: '#C4BEB1',
    other: '#D2CDC0'
  };

  const ADAPTIVE_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100];

  // Helper geometry functions
  function computePolygonArea(poly) {
    if (!poly || poly.length < 3) return 0;
    let area = 0;
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i];
      const [x2, y2] = poly[(i + 1) % poly.length];
      area += x1 * y2 - x2 * y1;
    }
    return Math.abs(area) / 2;
  }

  function computePolygonCentroid(poly) {
    if (!poly || poly.length < 3) return [0, 0];
    let cx = 0, cy = 0;
    for (let i = 0; i < poly.length; i++) {
      cx += poly[i][0];
      cy += poly[i][1];
    }
    return [cx / poly.length, cy / poly.length];
  }

  function wallLineToPolygon(x1, y1, x2, y2, thickness) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.hypot(dx, dy);
    if (len < 0.001) return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
    const nx = (-dy / len) * (thickness / 2);
    const ny = (dx / len) * (thickness / 2);
    return [
      [Number((x1 - nx).toFixed(3)), Number((y1 - ny).toFixed(3))],
      [Number((x2 - nx).toFixed(3)), Number((y2 - ny).toFixed(3))],
      [Number((x2 + nx).toFixed(3)), Number((y2 + ny).toFixed(3))],
      [Number((x1 + nx).toFixed(3)), Number((y1 + ny).toFixed(3))]
    ];
  }

  class FloorPlanEditor {
    constructor() {
      // DOM Elements
      this.view = document.getElementById('editor-view');
      this.container = document.getElementById('editor-canvas-container');
      this.svg = document.getElementById('editor-canvas');
      this.viewportGroup = document.getElementById('editor-viewport');
      this.gridGroup = document.getElementById('editor-grid');
      this.roomsGroup = document.getElementById('editor-rooms');
      this.wallsGroup = document.getElementById('editor-walls');
      this.openingsGroup = document.getElementById('editor-openings');
      this.furnitureGroup = document.getElementById('editor-furniture');
      this.annotationsGroup = document.getElementById('editor-annotations');
      this.previewGroup = document.getElementById('editor-preview');
      this.selectionGroup = document.getElementById('editor-selection');

      // Screen-space Overlay Layers (Step 1 Approach a: 1:1 screen pixels)
      this.labelsOverlay = document.getElementById('editor-labels-overlay');
      this.rulerOverlay = document.getElementById('editor-ruler-overlay');

      // UI Panels & Overlays
      this.libraryPanel = document.getElementById('editor-library-panel');
      this.emptyState = document.getElementById('editor-empty-state');
      this.scaleBarLine = document.getElementById('editor-scale-bar-line');
      this.scaleBarLabel = document.getElementById('editor-scale-bar-label');
      this.propertiesPanel = document.getElementById('editor-properties-panel');
      this.propertiesContent = document.getElementById('editor-properties-content');
      this.propTitle = document.getElementById('editor-prop-title');

      // Status Bar Elements
      this.coordsLabel = document.getElementById('editor-coords');
      this.snapToggle = document.getElementById('editor-snap-toggle');
      this.snapSelect = document.getElementById('editor-snap-select');
      this.zoomLabel = document.getElementById('editor-zoom-label');
      this.toolLabel = document.getElementById('editor-active-tool');
      this.projectTitleInput = document.getElementById('editor-project-title');

      // Viewport State (Step 5: 50 px/m initial, 10 to 400 px/m limits)
      this.pan = { x: 300, y: 180 };
      this.zoom = 50.0;
      this.minZoom = 10.0;
      this.maxZoom = 400.0;

      // Interaction State
      this.activeTool = 'select'; // 'select' | 'wall' | 'room' | 'door' | 'window' | 'place' | 'text' | 'delete'
      this.armedTool = null;      // Armed tool from library
      this.snapEnabled = true;
      this.snapStep = 0.25;       // meters
      this.isPanning = false;
      this.isSpacePressed = false;
      this.isShiftPressed = false; // Step 4: Shift toggle for wall angle display
      this.panStart = { x: 0, y: 0 };
      this.currentMouse = { screenX: 0, screenY: 0, worldX: 0, worldY: 0, snappedX: 0, snappedY: 0 };

      // Drawing state
      this.activeWallStart = null;
      this.activeRoomPoints = [];

      // Selection state
      this.selectedEntity = null; // { type, id, data }

      // Core Data Model (Contract: scene.json)
      this.sceneData = {
        meta: {
          source: 'FloorPlan3D Editor',
          imageSize: [1200, 900],
          metersPerPixel: 0.02,
          wallHeight: 3.0,
          wallThickness: 0.20,
          projectName: 'Untitled Plan'
        },
        rooms: [],
        walls: [],
        doors: [],
        windows: [],
        furniture: []
      };

      this.init();
    }

    init() {
      if (!this.svg || !this.container) return;

      this.setupEventListeners();
      this.setupToolbar();
      this.setupLibraryPanel();
      this.setupEmptyState();
      this.setupPropertiesPanel();
      this.initDefaultView();
      this.updateEmptyState();
      this.renderSceneData();
      this.updateStatus();
    }

    // ------------------------------------------------------------------------
    // Step 2 & 5: Viewport, Default View & Low-Zoom LOD
    // ------------------------------------------------------------------------
    getContainerDimensions() {
      const rect = this.container.getBoundingClientRect();
      const w = rect.width > 50 ? rect.width : Math.max(400, window.innerWidth - 260);
      const h = rect.height > 50 ? rect.height : Math.max(300, window.innerHeight - 92);
      return { width: w, height: h };
    }

    initDefaultView() {
      const dims = this.getContainerDimensions();
      this.zoom = 50.0; // Strictly 50 px/m
      // Center a default 12m x 8m area in the middle of canvas
      this.pan.x = dims.width / 2 - 6.0 * this.zoom;
      this.pan.y = dims.height / 2 - 4.0 * this.zoom;
      this.updateViewportTransform();
    }

    onViewShown() {
      const hasObjects = (this.sceneData.rooms.length > 0 || this.sceneData.walls.length > 0);
      if (hasObjects) {
        this.fitContent();
      } else {
        this.initDefaultView();
      }
      this.updateScaleBar();
      this.updateStatus();
    }

    updateViewportTransform() {
      if (!this.viewportGroup) return;

      // Low-zoom simplification toggle (< 20 px/m)
      const isLowZoom = (this.zoom < 20);
      if (this.container) this.container.classList.toggle('lod-low', isLowZoom);
      if (this.svg) this.svg.classList.toggle('lod-low', isLowZoom);

      this.viewportGroup.setAttribute(
        'transform',
        `translate(${this.pan.x.toFixed(2)}, ${this.pan.y.toFixed(2)}) scale(${this.zoom.toFixed(4)})`
      );

      this.renderGrid();
      this.renderRulers();
      this.renderLabels();
      this.renderSelection();
      this.updateScaleBar();

      if (this.zoomLabel) {
        this.zoomLabel.textContent = `${Math.round((this.zoom / 50) * 100)}% (${this.zoom.toFixed(0)}px/m)`;
      }
    }

    updateScaleBar() {
      if (!this.scaleBarLine || !this.scaleBarLabel) return;
      const lengthM = this.zoom >= 35 ? 1 : 5;
      const pixelWidth = lengthM * this.zoom;
      this.scaleBarLine.style.width = `${Math.round(pixelWidth)}px`;
      this.scaleBarLabel.textContent = `${lengthM} m`;
    }

    // ------------------------------------------------------------------------
    // Step 3: Adaptive Metric Grid & Perimeter Rulers
    // ------------------------------------------------------------------------
    renderGrid() {
      if (!this.gridGroup || !this.container) return;

      const dims = this.getContainerDimensions();
      const minX = Math.floor((-this.pan.x) / this.zoom) - 2;
      const maxX = Math.ceil((dims.width - this.pan.x) / this.zoom) + 2;
      const minY = Math.floor((-this.pan.y) / this.zoom) - 2;
      const maxY = Math.ceil((dims.height - this.pan.y) / this.zoom) + 2;

      const rangeX = maxX - minX;
      const rangeY = maxY - minY;
      if (rangeX > 600 || rangeY > 600) return;

      let svgLines = '';

      // 1. Minor grid lines (0.25 m): fade out when spacing < 6 px (i.e. zoom < 24 px/m)
      if (this.zoom * 0.25 >= 6) {
        const step = this.snapStep >= 0.5 ? 0.5 : 0.25;
        for (let x = minX; x <= maxX; x += step) {
          if (Math.abs(x - Math.round(x)) > 0.01) {
            svgLines += `<line x1="${x}" y1="${minY}" x2="${x}" y2="${maxY}" class="svg-grid-line svg-grid-minor" />`;
          }
        }
        for (let y = minY; y <= maxY; y += step) {
          if (Math.abs(y - Math.round(y)) > 0.01) {
            svgLines += `<line x1="${minX}" y1="${y}" x2="${maxX}" y2="${y}" class="svg-grid-line svg-grid-minor" />`;
          }
        }
      }

      // 2. 1-meter grid lines: shown when spacing >= 10 px (i.e. zoom >= 10 px/m)
      if (this.zoom * 1.0 >= 10) {
        for (let x = minX; x <= maxX; x += 1) {
          if (Math.abs(x % 5) > 0.01) {
            svgLines += `<line x1="${x}" y1="${minY}" x2="${x}" y2="${maxY}" class="svg-grid-line svg-grid-major" />`;
          }
        }
        for (let y = minY; y <= maxY; y += 1) {
          if (Math.abs(y % 5) > 0.01) {
            svgLines += `<line x1="${minX}" y1="${y}" x2="${maxX}" y2="${y}" class="svg-grid-line svg-grid-major" />`;
          }
        }
      }

      // 3. 5-meter grid lines: shown ALWAYS
      const majorStartX = Math.floor(minX / 5) * 5;
      const majorEndX = Math.ceil(maxX / 5) * 5;
      const majorStartY = Math.floor(minY / 5) * 5;
      const majorEndY = Math.ceil(maxY / 5) * 5;

      for (let x = majorStartX; x <= majorEndX; x += 5) {
        svgLines += `<line x1="${x}" y1="${minY}" x2="${x}" y2="${maxY}" class="svg-grid-line svg-grid-submajor" />`;
      }
      for (let y = majorStartY; y <= majorEndY; y += 5) {
        svgLines += `<line x1="${minX}" y1="${y}" x2="${maxX}" y2="${y}" class="svg-grid-line svg-grid-submajor" />`;
      }

      // 4. Primary coordinate axes (X=0, Y=0 hairlines)
      svgLines += `<line x1="0" y1="${minY}" x2="0" y2="${maxY}" stroke="var(--ink)" stroke-width="1.2" opacity="0.35" vector-effect="non-scaling-stroke" />`;
      svgLines += `<line x1="${minX}" y1="0" x2="${maxX}" y2="0" stroke="var(--ink)" stroke-width="1.2" opacity="0.35" vector-effect="non-scaling-stroke" />`;
      svgLines += `<circle cx="0" cy="0" r="0.06" fill="var(--pigment)" vector-effect="non-scaling-stroke" />`;

      this.gridGroup.innerHTML = svgLines;
    }

    renderRulers() {
      if (!this.rulerOverlay) return;

      const dims = this.getContainerDimensions();
      const minX = Math.floor((-this.pan.x) / this.zoom);
      const maxX = Math.ceil((dims.width - this.pan.x) / this.zoom);
      const minY = Math.floor((-this.pan.y) / this.zoom);
      const maxY = Math.ceil((dims.height - this.pan.y) / this.zoom);

      // Choose adaptive step from [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100] m
      // so labels are at least 80 px apart and at most ~15 labels per axis
      let step = 100;
      for (const s of ADAPTIVE_STEPS) {
        const pxGap = s * this.zoom;
        const countX = (maxX - minX) / s;
        const countY = (maxY - minY) / s;
        if (pxGap >= 80 && countX <= 15 && countY <= 15) {
          step = s;
          break;
        }
      }
      if (step * this.zoom < 80) {
        step = ADAPTIVE_STEPS.find(s => s * this.zoom >= 80) || 100;
      }

      let html = '';

      // 1. Top Ruler Strip (X Axis)
      html += `<rect x="0" y="0" width="${dims.width}" height="22" class="editor-ruler-strip" />`;
      const startX = Math.ceil(minX / step) * step;
      for (let x = startX; x <= maxX; x += step) {
        const sx = x * this.zoom + this.pan.x;
        if (sx >= 35 && sx <= dims.width - 25) {
          const isOrigin = Math.abs(x) < 0.001;
          html += `<line x1="${sx}" y1="12" x2="${sx}" y2="22" class="editor-ruler-tick" stroke="${isOrigin ? 'var(--pigment)' : 'var(--ink-2)'}" />`;
          html += `<text x="${sx + 3}" y="15" class="editor-ruler-label" fill="${isOrigin ? 'var(--pigment)' : 'var(--muted)'}">${Number(x.toFixed(2))} m</text>`;
        }
      }

      // 2. Left Ruler Strip (Y Axis)
      html += `<rect x="0" y="0" width="30" height="${dims.height}" class="editor-ruler-strip" />`;
      const startY = Math.ceil(minY / step) * step;
      for (let y = startY; y <= maxY; y += step) {
        const sy = y * this.zoom + this.pan.y;
        if (sy >= 28 && sy <= dims.height - 15) {
          const isOrigin = Math.abs(y) < 0.001;
          html += `<line x1="20" y1="${sy}" x2="30" y2="${sy}" class="editor-ruler-tick" stroke="${isOrigin ? 'var(--pigment)' : 'var(--ink-2)'}" />`;
          html += `<text x="3" y="${sy - 3}" class="editor-ruler-label" fill="${isOrigin ? 'var(--pigment)' : 'var(--muted)'}">${Number(y.toFixed(2))} m</text>`;
        }
      }

      // 3. Top-Left Corner Box
      html += `<rect x="0" y="0" width="30" height="22" class="editor-ruler-corner" />`;
      html += `<text x="7" y="15" font-family="'Azeret Mono', monospace" font-size="9" font-weight="700" fill="var(--muted)">m</text>`;

      this.rulerOverlay.innerHTML = html;
    }

    // ------------------------------------------------------------------------
    // Step 1: Constant Screen-Size Labels (Approach a: Screen Overlay Layer)
    // ------------------------------------------------------------------------
    renderLabels() {
      if (!this.labelsOverlay) return;
      const dims = this.getContainerDimensions();
      let html = '';

      // 1. Room Labels & Live Areas (12px / 10px screen size)
      (this.sceneData.rooms || []).forEach(room => {
        const poly = room.polygon || [];
        if (poly.length < 3) return;

        const [cx, cy] = computePolygonCentroid(poly);
        const sx = cx * this.zoom + this.pan.x;
        const sy = cy * this.zoom + this.pan.y;

        // Render if roughly visible in canvas viewport
        if (sx >= -100 && sx <= dims.width + 100 && sy >= -50 && sy <= dims.height + 50) {
          const areaM2 = computePolygonArea(poly);
          html += `
            <g class="editor-room-label-group">
              <text x="${sx}" y="${sy - 4}" class="editor-canvas-label editor-room-title">
                ${room.label || room.type || 'Room'}
              </text>
              <text x="${sx}" y="${sy + 10}" class="editor-canvas-label editor-room-area">
                ${areaM2.toFixed(1)} m²
              </text>
            </g>
          `;
        }
      });

      // 2. Selection Handles (Fixed 8px screen squares, Step 2)
      if (this.selectedEntity) {
        const bbox = this.getEntityBoundingBox(this.selectedEntity);
        if (bbox) {
          const tl = { x: bbox.minX * this.zoom + this.pan.x, y: bbox.minY * this.zoom + this.pan.y };
          const tr = { x: bbox.maxX * this.zoom + this.pan.x, y: bbox.minY * this.zoom + this.pan.y };
          const br = { x: bbox.maxX * this.zoom + this.pan.x, y: bbox.maxY * this.zoom + this.pan.y };
          const bl = { x: bbox.minX * this.zoom + this.pan.x, y: bbox.maxY * this.zoom + this.pan.y };

          html += `
            <rect x="${tl.x - 4}" y="${tl.y - 4}" width="8" height="8" class="editor-screen-handle" />
            <rect x="${tr.x - 4}" y="${tr.y - 4}" width="8" height="8" class="editor-screen-handle" />
            <rect x="${br.x - 4}" y="${br.y - 4}" width="8" height="8" class="editor-screen-handle" />
            <rect x="${bl.x - 4}" y="${bl.y - 4}" width="8" height="8" class="editor-screen-handle" />
          `;
        }
      }

      this.labelsOverlay.innerHTML = html;
    }

    getEntityBoundingBox(selected) {
      const { type, data } = selected;
      if (!data) return null;

      if (type === 'room' || type === 'wall') {
        const poly = data.polygon || [];
        if (poly.length >= 2) {
          let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
          poly.forEach(([x, y]) => {
            minX = Math.min(minX, x); maxX = Math.max(maxX, x);
            minY = Math.min(minY, y); maxY = Math.max(maxY, y);
          });
          return { minX, maxX, minY, maxY };
        }
      } else if (type === 'door' || type === 'window') {
        if (data.center) {
          const hw = (data.width || 1) / 2;
          return {
            minX: data.center[0] - hw,
            maxX: data.center[0] + hw,
            minY: data.center[1] - 0.2,
            maxY: data.center[1] + 0.2
          };
        }
      } else if (type === 'furniture') {
        if (data.center && data.size) {
          const hw = (data.size[0] || 1) / 2;
          const hd = (data.size[1] || 1) / 2;
          return {
            minX: data.center[0] - hw,
            maxX: data.center[0] + hw,
            minY: data.center[1] - hd,
            maxY: data.center[1] + hd
          };
        }
      }
      return null;
    }

    // ------------------------------------------------------------------------
    // Step 4: Live Wall Length Label (Horizontal 11px Badge, Offset 12px)
    // ------------------------------------------------------------------------
    updateLiveDrawingPreview() {
      if (!this.previewGroup) return;

      if (this.activeTool === 'wall' && this.activeWallStart) {
        const [x1, y1] = this.activeWallStart;
        const x2 = this.currentMouse.snappedX;
        const y2 = this.currentMouse.snappedY;

        // Screen space endpoints
        const p1x = x1 * this.zoom + this.pan.x;
        const p1y = y1 * this.zoom + this.pan.y;
        const p2x = x2 * this.zoom + this.pan.x;
        const p2y = y2 * this.zoom + this.pan.y;

        const worldLen = Math.hypot(x2 - x1, y2 - y1);
        const screenDx = p2x - p1x;
        const screenDy = p2y - p1y;
        const screenDist = Math.hypot(screenDx, screenDy);

        // Screen midpoint
        const midX = (p1x + p2x) / 2;
        const midY = (p1y + p2y) / 2;

        // Normal offset by 12px in screen space
        let nx = 0, ny = -1;
        if (screenDist > 0.001) {
          nx = -screenDy / screenDist;
          ny = screenDx / screenDist;
          if (ny > 0) { nx = -nx; ny = -ny; } // Keep label upright/above line
        }
        const lblX = midX + nx * 14;
        const lblY = midY + ny * 14;

        // Text formatting: "3.25 m" or "3.25 m  45°" when Shift held
        let labelText = `${worldLen.toFixed(2)} m`;
        if (this.isShiftPressed) {
          const angleDeg = Math.round(((Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI) + 360) % 360);
          labelText += `  ${angleDeg}°`;
        }

        const badgeW = Math.max(56, labelText.length * 7.5 + 16);
        const badgeH = 20;

        // World-space guide line with vector-effect: non-scaling-stroke
        this.previewGroup.innerHTML = `
          <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"
                stroke="var(--pigment)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
        `;

        // Render live wall badge in screen-space overlay (11px, horizontal, bone background)
        if (this.labelsOverlay) {
          this.renderLabels(); // Refresh existing room labels
          this.labelsOverlay.insertAdjacentHTML('beforeend', `
            <g id="editor-active-wall-badge">
              <rect x="${lblX - badgeW/2}" y="${lblY - badgeH/2}" width="${badgeW}" height="${badgeH}"
                    class="editor-wall-badge-bg" />
              <text x="${lblX}" y="${lblY + 4}" class="editor-wall-badge-text">
                ${labelText}
              </text>
              <!-- Fixed 8px snap markers at endpoints -->
              <rect x="${p1x - 4}" y="${p1y - 4}" width="8" height="8" fill="var(--pigment)" />
              <rect x="${p2x - 4}" y="${p2y - 4}" width="8" height="8" fill="var(--pigment)" />
            </g>
          `);
        }
      } else if (this.activeTool === 'room' && this.activeRoomPoints.length > 0) {
        const pts = [...this.activeRoomPoints, [this.currentMouse.snappedX, this.currentMouse.snappedY]];
        const pointsStr = pts.map(p => `${p[0]},${p[1]}`).join(' ');
        this.previewGroup.innerHTML = `
          <polyline points="${pointsStr}"
                    fill="none"
                    stroke="var(--pigment)"
                    stroke-width="1.5"
                    stroke-dasharray="4 3"
                    vector-effect="non-scaling-stroke" />
        `;
      } else {
        if (this.previewGroup) this.previewGroup.innerHTML = '';
      }
    }

    // ------------------------------------------------------------------------
    // Step 2 & 5: Fit Content & Camera Navigation
    // ------------------------------------------------------------------------
    fitContent() {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;

      this.sceneData.rooms.forEach(room => {
        (room.polygon || []).forEach(([x, y]) => {
          minX = Math.min(minX, x); maxX = Math.max(maxX, x);
          minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        });
      });

      this.sceneData.walls.forEach(w => {
        (w.polygon || []).forEach(([x, y]) => {
          minX = Math.min(minX, x); maxX = Math.max(maxX, x);
          minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        });
      });

      this.sceneData.doors.forEach(d => {
        if (d.center) {
          minX = Math.min(minX, d.center[0] - 0.5); maxX = Math.max(maxX, d.center[0] + 0.5);
          minY = Math.min(minY, d.center[1] - 0.5); maxY = Math.max(maxY, d.center[1] + 0.5);
        }
      });

      this.sceneData.furniture.forEach(f => {
        if (f.center && f.size) {
          const hw = (f.size[0] || 1) / 2;
          const hd = (f.size[1] || 1) / 2;
          minX = Math.min(minX, f.center[0] - hw); maxX = Math.max(maxX, f.center[0] + hw);
          minY = Math.min(minY, f.center[1] - hd); maxY = Math.max(maxY, f.center[1] + hd);
        }
      });

      const dims = this.getContainerDimensions();

      if (!Number.isFinite(minX)) {
        // Step 5: Initial and Fit view for empty canvas must be 50 px/m centered on 12m x 8m area
        this.zoom = 50.0;
        this.pan.x = dims.width / 2 - 6.0 * this.zoom;
        this.pan.y = dims.height / 2 - 4.0 * this.zoom;
        this.updateViewportTransform();
        return;
      }

      const padding = 60;
      const availW = Math.max(100, dims.width - padding * 2);
      const availH = Math.max(100, dims.height - padding * 2);
      const spanW = Math.max(2, (maxX - minX) * 1.1); // 10% padding
      const spanH = Math.max(2, (maxY - minY) * 1.1);

      this.zoom = Math.max(this.minZoom, Math.min(160, Math.min(availW / spanW, availH / spanH)));
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      this.pan.x = dims.width / 2 - cx * this.zoom;
      this.pan.y = dims.height / 2 - cy * this.zoom;

      this.updateViewportTransform();
    }

    zoomAt(factor, clientX, clientY) {
      const rect = this.svg.getBoundingClientRect();
      const mouseX = clientX - rect.left;
      const mouseY = clientY - rect.top;

      const worldBefore = {
        x: (mouseX - this.pan.x) / this.zoom,
        y: (mouseY - this.pan.y) / this.zoom
      };

      const newZoom = Math.max(this.minZoom, Math.min(this.maxZoom, this.zoom * factor));
      if (newZoom === this.zoom) return;

      this.zoom = newZoom;
      this.pan.x = mouseX - worldBefore.x * this.zoom;
      this.pan.y = mouseY - worldBefore.y * this.zoom;

      this.updateViewportTransform();
    }

    screenToWorld(screenX, screenY) {
      const rect = this.svg.getBoundingClientRect();
      const localX = screenX - rect.left;
      const localY = screenY - rect.top;
      return {
        x: (localX - this.pan.x) / this.zoom,
        y: (localY - this.pan.y) / this.zoom
      };
    }

    snap(val, step) {
      if (!this.snapEnabled) return Math.round(val * 1000) / 1000;
      const s = step || this.snapStep;
      return Math.round(val / s) * s;
    }

    snapPoint(worldPt) {
      return {
        x: this.snap(worldPt.x, this.snapStep),
        y: this.snap(worldPt.y, this.snapStep)
      };
    }

    // ------------------------------------------------------------------------
    // Step 3: Empty State Handling
    // ------------------------------------------------------------------------
    setupEmptyState() {
      const btnDraw = document.getElementById('btn-empty-draw-walls');
      const btnTemplate = document.getElementById('btn-empty-template');
      const btnLoadAi = document.getElementById('btn-empty-load-ai');
      const btnLoadSample = document.getElementById('btn-empty-load-sample');

      if (btnDraw) btnDraw.addEventListener('click', () => this.setTool('wall'));
      if (btnTemplate) btnTemplate.addEventListener('click', () => this.loadApartmentTemplate());
      if (btnLoadAi) btnLoadAi.addEventListener('click', () => this.loadAiResult());
      if (btnLoadSample) btnLoadSample.addEventListener('click', () => this.loadSampleScene());
    }

    updateEmptyState() {
      if (!this.emptyState) return;
      const totalCount =
        this.sceneData.rooms.length +
        this.sceneData.walls.length +
        this.sceneData.doors.length +
        this.sceneData.windows.length +
        this.sceneData.furniture.length;

      if (totalCount === 0) {
        this.emptyState.classList.remove('is-hidden');
      } else {
        this.emptyState.classList.add('is-hidden');
      }
    }

    loadSampleScene() {
      fetch('/api/sample')
        .then(res => res.json())
        .then(data => {
          if (data && data.scene) {
            this.sceneData = data.scene;
            if (!this.sceneData.furniture) this.sceneData.furniture = [];
            this.renderSceneData();
            this.updateEmptyState();
            this.fitContent();
            this.selectEntity(null);
          }
        })
        .catch(err => {
          console.warn('Fallback fetch /samples/sample_scene.json:', err);
          fetch('/samples/sample_scene.json')
            .then(res => res.json())
            .then(scene => {
              this.sceneData = scene;
              if (!this.sceneData.furniture) this.sceneData.furniture = [];
              this.renderSceneData();
              this.updateEmptyState();
              this.fitContent();
              this.selectEntity(null);
            });
        });
    }

    loadAiResult() {
      if (window.currentScene && window.currentScene.rooms && window.currentScene.rooms.length > 0) {
        this.sceneData = JSON.parse(JSON.stringify(window.currentScene));
        if (!this.sceneData.furniture) this.sceneData.furniture = [];
        this.renderSceneData();
        this.updateEmptyState();
        this.fitContent();
      } else {
        this.loadSampleScene();
      }
    }

    loadApartmentTemplate() {
      this.sceneData = {
        meta: {
          source: 'Template Studio',
          imageSize: [1000, 800],
          metersPerPixel: 0.02,
          wallHeight: 3.0,
          wallThickness: 0.20,
          projectName: 'Modern 2-Room Studio'
        },
        rooms: [
          { id: 'r1', type: 'room', label: 'Living Room', confidence: 0.95, polygon: [[1.0, 1.0], [7.0, 1.0], [7.0, 6.0], [1.0, 6.0]] },
          { id: 'r2', type: 'room', label: 'Master Bedroom', confidence: 0.94, polygon: [[7.0, 1.0], [12.0, 1.0], [12.0, 6.0], [7.0, 6.0]] },
          { id: 'r3', type: 'restroom', label: 'Bathroom', confidence: 0.92, polygon: [[1.0, 6.0], [4.5, 6.0], [4.5, 9.5], [1.0, 9.5]] },
          { id: 'r4', type: 'corridor', label: 'Hallway', confidence: 0.97, polygon: [[4.5, 6.0], [12.0, 6.0], [12.0, 9.5], [4.5, 9.5]] }
        ],
        walls: [
          { id: 'w1', polygon: wallLineToPolygon(1.0, 1.0, 12.0, 1.0, 0.20) },
          { id: 'w2', polygon: wallLineToPolygon(12.0, 1.0, 12.0, 9.5, 0.20) },
          { id: 'w3', polygon: wallLineToPolygon(12.0, 9.5, 1.0, 9.5, 0.20) },
          { id: 'w4', polygon: wallLineToPolygon(1.0, 9.5, 1.0, 1.0, 0.20) },
          { id: 'w5', polygon: wallLineToPolygon(7.0, 1.0, 7.0, 6.0, 0.15) },
          { id: 'w6', polygon: wallLineToPolygon(1.0, 6.0, 12.0, 6.0, 0.15) },
          { id: 'w7', polygon: wallLineToPolygon(4.5, 6.0, 4.5, 9.5, 0.15) }
        ],
        doors: [
          { id: 'd1', center: [7.0, 3.5], width: 0.9, angle: 1.5708, connects: ['r1', 'r2'] },
          { id: 'd2', center: [3.5, 6.0], width: 0.8, angle: 0, connects: ['r1', 'r3'] },
          { id: 'd3', center: [5.5, 6.0], width: 0.9, angle: 0, connects: ['r1', 'r4'] },
          { id: 'd4', center: [8.5, 9.5], width: 1.0, angle: 0, connects: ['r4', 'outside'] }
        ],
        windows: [
          { id: 'win1', center: [4.0, 1.0], width: 1.6, angle: 0 },
          { id: 'win2', center: [9.5, 1.0], width: 1.6, angle: 0 },
          { id: 'win3', center: [1.0, 3.5], width: 1.2, angle: 1.5708 }
        ],
        furniture: [
          { id: 'f1', kind: 'sofa', center: [3.5, 3.5], size: [2.1, 0.9], angle: 0 },
          { id: 'f2', kind: 'bed', center: [9.5, 3.2], size: [1.6, 2.0], angle: 0 },
          { id: 'f3', kind: 'dining-table', center: [8.0, 7.8], size: [1.6, 0.9], angle: 0 }
        ]
      };

      this.renderSceneData();
      this.updateEmptyState();
      this.fitContent();
      this.selectEntity(null);
    }

    // ------------------------------------------------------------------------
    // Step 4: Left Element Library Panel
    // ------------------------------------------------------------------------
    setupLibraryPanel() {
      if (this.libToggleBtn) {
        this.libToggleBtn.addEventListener('click', () => {
          if (!this.libraryPanel) return;
          const isCollapsed = this.libraryPanel.classList.toggle('is-collapsed');
          if (this.libToggleIcon) {
            this.libToggleIcon.innerHTML = isCollapsed ? '&raquo;' : '&laquo;';
          }
          setTimeout(() => this.fitContent(), 220);
        });
      }

      document.querySelectorAll('.editor-accordion-title').forEach(btn => {
        btn.addEventListener('click', () => {
          const section = btn.closest('.editor-accordion-section');
          if (section) section.classList.toggle('is-open');
        });
      });

      document.querySelectorAll('.editor-lib-cell').forEach(cell => {
        cell.addEventListener('click', () => {
          this.armLibraryItem(cell, cell.dataset.libTool);
        });
      });
    }

    armLibraryItem(cellElem, toolId) {
      document.querySelectorAll('.editor-lib-cell').forEach(c => c.classList.remove('is-armed'));

      if (this.armedTool === toolId) {
        this.armedTool = null;
        this.setTool('select');
        return;
      }

      cellElem.classList.add('is-armed');
      this.armedTool = toolId;

      if (toolId.startsWith('wall-')) this.setTool('wall');
      else if (toolId.startsWith('door-')) this.setTool('door');
      else if (toolId.startsWith('window-')) this.setTool('window');
      else if (toolId.startsWith('furniture-') || toolId.startsWith('structure-') || toolId.startsWith('stairs-')) this.setTool('place');
      else if (toolId.startsWith('text-')) this.setTool('text');
    }

    // ------------------------------------------------------------------------
    // Object Rendering Engine (World-space SVG elements)
    // ------------------------------------------------------------------------
    renderSceneData() {
      this.renderRooms();
      this.renderWalls();
      this.renderOpenings();
      this.renderFurniture();
      this.renderLabels();
      this.renderSelection();
      this.updateEmptyState();
    }

    renderRooms() {
      if (!this.roomsGroup) return;
      let html = '';

      (this.sceneData.rooms || []).forEach(room => {
        const poly = room.polygon || [];
        if (poly.length < 3) return;

        const pointsStr = poly.map(pt => `${pt[0]},${pt[1]}`).join(' ');
        const roomType = room.type || 'room';
        const fillColor = ROOM_COLORS[roomType] || ROOM_COLORS.room;

        html += `
          <g class="editor-room-group" data-room-id="${room.id}">
            <polygon points="${pointsStr}"
                     fill="${fillColor}"
                     fill-opacity="0.55"
                     class="editor-room-poly editor-hit-room"
                     data-entity-type="room"
                     data-entity-id="${room.id}" />
          </g>
        `;
      });

      this.roomsGroup.innerHTML = html;
    }

    renderWalls() {
      if (!this.wallsGroup) return;
      let html = '';

      (this.sceneData.walls || []).forEach(wall => {
        const poly = wall.polygon || [];
        if (poly.length < 3) return;

        const pointsStr = poly.map(pt => `${pt[0]},${pt[1]}`).join(' ');

        html += `
          <g class="editor-wall-group" data-wall-id="${wall.id}">
            <polygon points="${pointsStr}"
                     class="editor-wall-poly" />
            <!-- Invisible hit-test wrapper (14px clickable area) -->
            <polygon points="${pointsStr}"
                     fill="transparent"
                     stroke="transparent"
                     stroke-width="0.3"
                     pointer-events="all"
                     class="editor-hit-wall"
                     data-entity-type="wall"
                     data-entity-id="${wall.id}" />
          </g>
        `;
      });

      this.wallsGroup.innerHTML = html;
    }

    renderOpenings() {
      if (!this.openingsGroup) return;
      let html = '';

      // Doors
      (this.sceneData.doors || []).forEach(door => {
        if (!door.center) return;
        const [cx, cy] = door.center;
        const w = door.width || 0.9;
        const ang = door.angle || door.rotation || 0;
        const flip = door.flip ? -1 : 1;

        // Render door leaf and swing arc (swing arc simplified under 20 px/m via .editor-door-arc)
        html += `
          <g class="editor-door-group" transform="translate(${cx}, ${cy}) rotate(${(ang * 180 / Math.PI).toFixed(1)})" data-door-id="${door.id}">
            <path d="M ${-w/2} 0 A ${w} ${w} 0 0 1 ${-w/2 + w * Math.cos(Math.PI/2 * flip)} ${w * Math.sin(Math.PI/2 * flip)}"
                  fill="none"
                  stroke="var(--ink)"
                  stroke-width="1"
                  stroke-dasharray="4 3"
                  vector-effect="non-scaling-stroke"
                  class="editor-door-arc"
                  pointer-events="none" />
            <line x1="${-w/2}" y1="0" x2="${-w/2}" y2="${w * flip}"
                  stroke="#5A4636"
                  stroke-width="1.5"
                  vector-effect="non-scaling-stroke"
                  pointer-events="none" />
            <line x1="${-w/2}" y1="0" x2="${w/2}" y2="0"
                  stroke="#5A4636"
                  stroke-width="2"
                  vector-effect="non-scaling-stroke" />
            <rect x="${-w/2 - 0.1}" y="${-0.25}" width="${w + 0.2}" height="0.5"
                  fill="transparent"
                  stroke="transparent"
                  pointer-events="all"
                  class="editor-hit-opening"
                  data-entity-type="door"
                  data-entity-id="${door.id}" />
          </g>
        `;
      });

      // Windows
      (this.sceneData.windows || []).forEach(win => {
        if (!win.center) return;
        const [cx, cy] = win.center;
        const w = win.width || 1.2;
        const ang = win.angle || win.rotation || 0;

        html += `
          <g class="editor-window-group" transform="translate(${cx}, ${cy}) rotate(${(ang * 180 / Math.PI).toFixed(1)})" data-window-id="${win.id}">
            <rect x="${-w/2}" y="-0.08" width="${w}" height="0.16"
                  fill="#A9B4B6"
                  fill-opacity="0.55"
                  stroke="var(--ink)"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke" />
            <line x1="${-w/2}" y1="0" x2="${w/2}" y2="0"
                  stroke="var(--ink)"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke" />
            <rect x="${-w/2 - 0.1}" y="-0.2" width="${w + 0.2}" height="0.4"
                  fill="transparent"
                  stroke="transparent"
                  pointer-events="all"
                  class="editor-hit-opening"
                  data-entity-type="window"
                  data-entity-id="${win.id}" />
          </g>
        `;
      });

      this.openingsGroup.innerHTML = html;
    }

    renderFurniture() {
      if (!this.furnitureGroup) return;
      let html = '';

      (this.sceneData.furniture || []).forEach(item => {
        if (!item.center || !item.size) return;
        const [cx, cy] = item.center;
        const [w, d] = item.size;
        const ang = item.angle || 0;
        const hw = w / 2;
        const hd = d / 2;

        html += `
          <g class="editor-furniture-group" transform="translate(${cx}, ${cy}) rotate(${(ang * 180 / Math.PI).toFixed(1)})" data-furniture-id="${item.id}">
            <rect x="${-hw}" y="${-hd}" width="${w}" height="${d}"
                  fill="var(--ground-2)"
                  stroke="var(--ink)"
                  stroke-width="1"
                  vector-effect="non-scaling-stroke" />
            <!-- Inner detail lines (simplified under 20 px/m) -->
            <line x1="${-hw + 0.1}" y1="${-hd + 0.1}" x2="${hw - 0.1}" y2="${-hd + 0.1}"
                  stroke="var(--ink)" stroke-width="0.75" vector-effect="non-scaling-stroke" class="editor-furniture-detail" />
            <rect x="${-hw}" y="${-hd}" width="${w}" height="${d}"
                  fill="transparent"
                  stroke="transparent"
                  pointer-events="all"
                  class="editor-hit-furniture"
                  data-entity-type="furniture"
                  data-entity-id="${item.id}" />
          </g>
        `;
      });

      this.furnitureGroup.innerHTML = html;
    }

    // ------------------------------------------------------------------------
    // Selection Bounding Box & Inspector
    // ------------------------------------------------------------------------
    selectEntity(entity) {
      this.selectedEntity = entity;
      this.renderSelection();
      this.renderLabels();
      this.updatePropertiesPanel();
    }

    renderSelection() {
      if (!this.selectionGroup) return;
      if (!this.selectedEntity) {
        this.selectionGroup.innerHTML = '';
        return;
      }

      const bbox = this.getEntityBoundingBox(this.selectedEntity);
      if (!bbox) {
        this.selectionGroup.innerHTML = '';
        return;
      }

      const w = bbox.maxX - bbox.minX;
      const h = bbox.maxY - bbox.minY;

      // Selection outline stays a crisp 1.5px non-scaling stroke
      this.selectionGroup.innerHTML = `
        <rect x="${bbox.minX}" y="${bbox.minY}" width="${w}" height="${h}"
              class="editor-selection-outline" />
      `;
    }

    setupPropertiesPanel() {
      const closeBtn = document.getElementById('btn-close-props');
      if (closeBtn) closeBtn.addEventListener('click', () => this.selectEntity(null));
    }

    updatePropertiesPanel() {
      if (!this.propertiesContent || !this.propTitle) return;

      if (!this.selectedEntity) {
        this.propTitle.textContent = 'PLAN OVERVIEW';
        const totalArea = (this.sceneData.rooms || []).reduce((sum, r) => sum + computePolygonArea(r.polygon), 0);
        this.propertiesContent.innerHTML = `
          <div class="editor-prop-group">
            <span class="editor-prop-label">PROJECT NAME</span>
            <span class="editor-prop-val">${this.sceneData.meta.projectName || 'Untitled Plan'}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">TOTAL AREA</span>
            <span class="editor-prop-val">${totalArea.toFixed(1)} m²</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">ROOMS</span>
            <span class="editor-prop-val">${this.sceneData.rooms.length}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">WALLS</span>
            <span class="editor-prop-val">${this.sceneData.walls.length}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">OPENINGS</span>
            <span class="editor-prop-val">${this.sceneData.doors.length + this.sceneData.windows.length}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">FURNITURE</span>
            <span class="editor-prop-val">${this.sceneData.furniture.length}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">WALL HEIGHT</span>
            <span class="editor-prop-val">3.00 m</span>
          </div>
        `;
        return;
      }

      const { type, id, data } = this.selectedEntity;

      if (type === 'room') {
        this.propTitle.textContent = 'ROOM ZONE';
        const areaM2 = computePolygonArea(data.polygon);
        const areaSqFt = (areaM2 * 10.7639).toFixed(0);

        this.propertiesContent.innerHTML = `
          <div class="editor-prop-group">
            <label class="editor-prop-label" for="prop-room-label">ROOM LABEL</label>
            <input id="prop-room-label" type="text" class="editor-prop-input" value="${data.label || ''}" />
          </div>
          <div class="editor-prop-group">
            <label class="editor-prop-label" for="prop-room-type">ROOM TYPE</label>
            <select id="prop-room-type" class="editor-prop-select">
              ${['classroom', 'lab', 'corridor', 'restroom', 'stairs', 'elevator', 'entrance', 'library', 'room', 'other']
                .map(t => `<option value="${t}" ${data.type === t ? 'selected' : ''}>${t.toUpperCase()}</option>`).join('')}
            </select>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">CALCULATED AREA</span>
            <span class="editor-prop-val">${areaM2.toFixed(1)} m² (${areaSqFt} sq ft)</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">VERTICES</span>
            <span class="editor-prop-val">${(data.polygon || []).length} Points</span>
          </div>
          <button type="button" id="prop-btn-delete" class="editor-prop-btn-danger">Delete Room [Del]</button>
        `;

        document.getElementById('prop-room-label').addEventListener('input', (e) => {
          data.label = e.target.value;
          this.renderLabels();
        });

        document.getElementById('prop-room-type').addEventListener('change', (e) => {
          data.type = e.target.value;
          this.renderRooms();
          this.renderLabels();
        });

      } else if (type === 'wall') {
        this.propTitle.textContent = 'WALL REGION';
        const poly = data.polygon || [];
        const lengthEstimate = poly.length >= 4 ? Math.hypot(poly[1][0] - poly[0][0], poly[1][1] - poly[0][1]) : 0;

        this.propertiesContent.innerHTML = `
          <div class="editor-prop-group">
            <span class="editor-prop-label">WALL ID</span>
            <span class="editor-prop-val">${id}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">EST. LENGTH</span>
            <span class="editor-prop-val">${lengthEstimate.toFixed(2)} m</span>
          </div>
          <div class="editor-prop-group">
            <label class="editor-prop-label" for="prop-wall-thickness">THICKNESS</label>
            <select id="prop-wall-thickness" class="editor-prop-select">
              <option value="0.10">0.10 m (Partition)</option>
              <option value="0.15">0.15 m (Interior)</option>
              <option value="0.20" selected>0.20 m (Exterior)</option>
              <option value="0.30">0.30 m (Structural)</option>
            </select>
          </div>
          <button type="button" id="prop-btn-delete" class="editor-prop-btn-danger">Delete Wall [Del]</button>
        `;

      } else if (type === 'door') {
        this.propTitle.textContent = 'DOOR OPENING';
        this.propertiesContent.innerHTML = `
          <div class="editor-prop-row">
            <span class="editor-prop-label">WIDTH</span>
            <span class="editor-prop-val">${(data.width || 0.9).toFixed(2)} m</span>
          </div>
          <div class="editor-prop-group">
            <button type="button" id="prop-btn-flip-swing" class="editor-prop-btn">Flip Swing Direction</button>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">CONNECTS</span>
            <span class="editor-prop-val">${(data.connects || ['-', '-']).join(' &harr; ')}</span>
          </div>
          <button type="button" id="prop-btn-delete" class="editor-prop-btn-danger">Delete Door [Del]</button>
        `;

        document.getElementById('prop-btn-flip-swing').addEventListener('click', () => {
          data.flip = !data.flip;
          this.renderOpenings();
          this.renderSelection();
        });

      } else if (type === 'window') {
        this.propTitle.textContent = 'WINDOW OPENING';
        this.propertiesContent.innerHTML = `
          <div class="editor-prop-row">
            <span class="editor-prop-label">WIDTH</span>
            <span class="editor-prop-val">${(data.width || 1.2).toFixed(2)} m</span>
          </div>
          <button type="button" id="prop-btn-delete" class="editor-prop-btn-danger">Delete Window [Del]</button>
        `;

      } else if (type === 'furniture') {
        this.propTitle.textContent = 'FURNITURE / FIXTURE';
        this.propertiesContent.innerHTML = `
          <div class="editor-prop-group">
            <span class="editor-prop-label">KIND</span>
            <span class="editor-prop-val">${(data.kind || 'fixture').toUpperCase()}</span>
          </div>
          <div class="editor-prop-row">
            <span class="editor-prop-label">SIZE</span>
            <span class="editor-prop-val">${data.size ? `${data.size[0]} × ${data.size[1]} m` : '1.0 × 1.0 m'}</span>
          </div>
          <div class="editor-prop-group">
            <button type="button" id="prop-btn-rotate" class="editor-prop-btn">Rotate 90&deg;</button>
          </div>
          <button type="button" id="prop-btn-delete" class="editor-prop-btn-danger">Delete Item [Del]</button>
        `;

        document.getElementById('prop-btn-rotate').addEventListener('click', () => {
          data.angle = ((data.angle || 0) + Math.PI / 2) % (Math.PI * 2);
          this.renderFurniture();
          this.renderSelection();
        });
      }

      const delBtn = document.getElementById('prop-btn-delete');
      if (delBtn) delBtn.addEventListener('click', () => this.deleteSelectedEntity());
    }

    deleteSelectedEntity() {
      if (!this.selectedEntity) return;
      const { type, id } = this.selectedEntity;

      if (type === 'room') this.sceneData.rooms = this.sceneData.rooms.filter(r => r.id !== id);
      else if (type === 'wall') this.sceneData.walls = this.sceneData.walls.filter(w => w.id !== id);
      else if (type === 'door') this.sceneData.doors = this.sceneData.doors.filter(d => d.id !== id);
      else if (type === 'window') this.sceneData.windows = this.sceneData.windows.filter(w => w.id !== id);
      else if (type === 'furniture') this.sceneData.furniture = this.sceneData.furniture.filter(f => f.id !== id);

      this.selectEntity(null);
      this.renderSceneData();
    }

    // ------------------------------------------------------------------------
    // Toolbar & Active Tool Switcher
    // ------------------------------------------------------------------------
    setTool(toolName) {
      this.activeTool = toolName;
      document.querySelectorAll('[data-editor-tool]').forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.editorTool === toolName);
      });
      if (this.toolLabel) {
        const toolNames = {
          select: 'SELECT [V]',
          wall: 'WALL [W]',
          room: 'ROOM OUTLINE [R]',
          door: 'DOOR [D]',
          window: 'WINDOW [N]',
          place: 'PLACE ITEM',
          text: 'TEXT [T]',
          delete: 'DELETE [DEL]'
        };
        this.toolLabel.textContent = `TOOL: ${toolNames[toolName] || toolName.toUpperCase()}`;
      }

      if (toolName !== 'wall') this.activeWallStart = null;
      if (toolName !== 'room') this.activeRoomPoints = [];
      if (this.previewGroup) this.previewGroup.innerHTML = '';
      this.renderLabels();
    }

    setupToolbar() {
      document.querySelectorAll('[data-editor-tool]').forEach(btn => {
        btn.addEventListener('click', () => this.setTool(btn.dataset.editorTool));
      });

      document.querySelectorAll('[data-editor-action]').forEach(btn => {
        btn.addEventListener('click', () => {
          const action = btn.dataset.editorAction;
          if (action === 'fit') this.fitContent();
          else if (action === 'zoom-in') this.zoomAt(1.25, window.innerWidth / 2, window.innerHeight / 2);
          else if (action === 'zoom-out') this.zoomAt(0.8, window.innerWidth / 2, window.innerHeight / 2);
        });
      });

      const sendTo3dBtn = document.getElementById('btn-editor-send-to-3d');
      if (sendTo3dBtn) {
        sendTo3dBtn.addEventListener('click', () => this.sendTo3dViewer());
      }
    }

    sendTo3dViewer() {
      window.currentScene = JSON.parse(JSON.stringify(this.sceneData));
      if (typeof window.renderScene === 'function') {
        window.renderScene(window.currentScene);
      }
      if (window.FloorPlan3DStudio && typeof window.FloorPlan3DStudio.switchToAppView === 'function') {
        window.FloorPlan3DStudio.switchToAppView();
      }
    }

    // ------------------------------------------------------------------------
    // Pointer Events & Drawing Handlers
    // ------------------------------------------------------------------------
    setupEventListeners() {
      // Wheel Zoom
      this.container.addEventListener('wheel', (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 0.87;
        this.zoomAt(factor, e.clientX, e.clientY);
      }, { passive: false });

      // Pointerdown
      this.container.addEventListener('pointerdown', (e) => {
        if (e.button === 1 || (e.button === 0 && this.isSpacePressed)) {
          e.preventDefault();
          this.isPanning = true;
          this.panStart = { x: e.clientX - this.pan.x, y: e.clientY - this.pan.y };
          this.container.classList.add('is-panning');
          return;
        }

        if (e.button === 0) {
          const world = this.screenToWorld(e.clientX, e.clientY);
          const snapped = this.snapPoint(world);

          if (this.activeTool === 'select') this.handleSelectPointerdown(e);
          else if (this.activeTool === 'wall') this.handleWallPointerdown(snapped);
          else if (this.activeTool === 'room') this.handleRoomPointerdown(snapped);
          else if (this.activeTool === 'door') this.handlePlaceDoor(snapped);
          else if (this.activeTool === 'window') this.handlePlaceWindow(snapped);
          else if (this.activeTool === 'place') this.handlePlaceArmedItem(snapped);
          else if (this.activeTool === 'delete') this.handleDeletePointerdown(e);
        }
      });

      window.addEventListener('pointermove', (e) => {
        if (this.isPanning) {
          this.pan.x = e.clientX - this.panStart.x;
          this.pan.y = e.clientY - this.panStart.y;
          this.updateViewportTransform();
          return;
        }

        const rawWorld = this.screenToWorld(e.clientX, e.clientY);
        const snapped = this.snapPoint(rawWorld);

        this.currentMouse = {
          screenX: e.clientX,
          screenY: e.clientY,
          worldX: rawWorld.x,
          worldY: rawWorld.y,
          snappedX: snapped.x,
          snappedY: snapped.y
        };

        this.updateStatus();
        this.updateLiveDrawingPreview();
      });

      window.addEventListener('pointerup', (e) => {
        if (this.isPanning) {
          this.isPanning = false;
          this.container.classList.remove('is-panning');
        }
      });

      window.addEventListener('resize', () => {
        this.updateViewportTransform();
      });

      // Keyboard Shortcuts (Shift tracking for angle, Space for pan)
      window.addEventListener('keydown', (e) => {
        if (e.key === 'Shift' && !this.isShiftPressed) {
          this.isShiftPressed = true;
          this.updateLiveDrawingPreview();
        }

        const tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;

        if (e.code === 'Space' && !this.isSpacePressed) {
          this.isSpacePressed = true;
          this.container.classList.add('is-panning');
        } else if (e.key === 'v' || e.key === 'V') {
          this.setTool('select');
        } else if (e.key === 'w' || e.key === 'W') {
          this.setTool('wall');
        } else if (e.key === 'r' || e.key === 'R') {
          this.setTool('room');
        } else if (e.key === 'd' || e.key === 'D') {
          this.setTool('door');
        } else if (e.key === 'n' || e.key === 'N') {
          this.setTool('window');
        } else if (e.key === 't' || e.key === 'T') {
          this.setTool('text');
        } else if (e.key === 'Delete' || e.key === 'Backspace') {
          this.deleteSelectedEntity();
        } else if (e.key === 'Escape') {
          this.activeWallStart = null;
          this.activeRoomPoints = [];
          if (this.previewGroup) this.previewGroup.innerHTML = '';
          this.renderLabels();
          this.selectEntity(null);
        } else if (e.key === 'f' || e.key === 'F') {
          this.fitContent();
        } else if (e.key === '+' || e.key === '=') {
          this.zoomAt(1.2, window.innerWidth / 2, window.innerHeight / 2);
        } else if (e.key === '-' || e.key === '_') {
          this.zoomAt(0.8, window.innerWidth / 2, window.innerHeight / 2);
        }
      });

      window.addEventListener('keyup', (e) => {
        if (e.key === 'Shift') {
          this.isShiftPressed = false;
          this.updateLiveDrawingPreview();
        }
        if (e.code === 'Space') {
          this.isSpacePressed = false;
          if (!this.isPanning) this.container.classList.remove('is-panning');
        }
      });

      window.addEventListener('blur', () => {
        this.isShiftPressed = false;
        this.isSpacePressed = false;
      });

      if (this.snapToggle) {
        this.snapToggle.addEventListener('change', (e) => {
          this.snapEnabled = e.target.checked;
        });
      }

      if (this.snapSelect) {
        this.snapSelect.addEventListener('change', (e) => {
          this.snapStep = parseFloat(e.target.value) || 0.25;
          this.renderGrid();
        });
      }

      if (this.projectTitleInput) {
        this.projectTitleInput.addEventListener('input', (e) => {
          this.sceneData.meta.projectName = e.target.value.trim() || 'Untitled Plan';
        });
      }
    }

    handleSelectPointerdown(e) {
      const target = e.target;
      const entityElem = target.closest('[data-entity-type]');

      if (entityElem) {
        const type = entityElem.dataset.entityType;
        const id = entityElem.dataset.entityId;
        let data = null;

        if (type === 'room') data = this.sceneData.rooms.find(r => r.id === id);
        else if (type === 'wall') data = this.sceneData.walls.find(w => w.id === id);
        else if (type === 'door') data = this.sceneData.doors.find(d => d.id === id);
        else if (type === 'window') data = this.sceneData.windows.find(w => w.id === id);
        else if (type === 'furniture') data = this.sceneData.furniture.find(f => f.id === id);

        if (data) {
          this.selectEntity({ type, id, data });
          return;
        }
      }

      this.selectEntity(null);
    }

    handleDeletePointerdown(e) {
      this.handleSelectPointerdown(e);
      if (this.selectedEntity) this.deleteSelectedEntity();
    }

    handleWallPointerdown(pt) {
      if (!this.activeWallStart) {
        this.activeWallStart = [pt.x, pt.y];
      } else {
        const [x1, y1] = this.activeWallStart;
        const x2 = pt.x;
        const y2 = pt.y;
        const len = Math.hypot(x2 - x1, y2 - y1);

        if (len >= 0.2) {
          const thickness = (this.armedTool === 'wall-interior') ? 0.15 : 0.20;
          const poly = wallLineToPolygon(x1, y1, x2, y2, thickness);
          const newWall = {
            id: `wall_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
            polygon: poly,
            holes: []
          };
          this.sceneData.walls.push(newWall);
          this.renderWalls();
          this.updateEmptyState();
          this.activeWallStart = [x2, y2];
        }
      }
    }

    handleRoomPointerdown(pt) {
      if (this.activeRoomPoints.length >= 3) {
        const [x0, y0] = this.activeRoomPoints[0];
        if (Math.hypot(pt.x - x0, pt.y - y0) < 0.4) {
          const newRoom = {
            id: `r_${Date.now()}`,
            type: 'room',
            label: `Room ${this.sceneData.rooms.length + 1}`,
            polygon: [...this.activeRoomPoints]
          };
          this.sceneData.rooms.push(newRoom);
          this.activeRoomPoints = [];
          if (this.previewGroup) this.previewGroup.innerHTML = '';
          this.renderRooms();
          this.renderLabels();
          this.updateEmptyState();
          this.setTool('select');
          this.selectEntity({ type: 'room', id: newRoom.id, data: newRoom });
          return;
        }
      }
      this.activeRoomPoints.push([pt.x, pt.y]);
    }

    handlePlaceDoor(pt) {
      const isDouble = (this.armedTool === 'door-double');
      const isSliding = (this.armedTool === 'door-sliding');
      const width = isDouble ? 1.6 : (isSliding ? 1.4 : 0.9);

      const newDoor = {
        id: `d_${Date.now()}`,
        center: [pt.x, pt.y],
        width: width,
        angle: 0,
        connects: ['room', 'outside']
      };
      this.sceneData.doors.push(newDoor);
      this.renderOpenings();
      this.updateEmptyState();
      this.selectEntity({ type: 'door', id: newDoor.id, data: newDoor });
    }

    handlePlaceWindow(pt) {
      const isWide = (this.armedTool === 'window-wide');
      const isDouble = (this.armedTool === 'window-double');
      const width = isWide ? 2.0 : (isDouble ? 1.5 : 1.0);

      const newWindow = {
        id: `win_${Date.now()}`,
        center: [pt.x, pt.y],
        width: width,
        angle: 0
      };
      this.sceneData.windows.push(newWindow);
      this.renderOpenings();
      this.updateEmptyState();
      this.selectEntity({ type: 'window', id: newWindow.id, data: newWindow });
    }

    handlePlaceArmedItem(pt) {
      if (!this.armedTool) return;
      const tool = this.armedTool;

      let kind = 'furniture';
      let size = [1.0, 1.0];

      if (tool === 'furniture-bed') { kind = 'bed'; size = [1.6, 2.0]; }
      else if (tool === 'furniture-sofa') { kind = 'sofa'; size = [2.1, 0.9]; }
      else if (tool === 'furniture-table') { kind = 'table'; size = [1.2, 0.6]; }
      else if (tool === 'furniture-chairs') { kind = 'chair'; size = [0.8, 0.8]; }
      else if (tool === 'furniture-stove') { kind = 'stove'; size = [0.6, 0.6]; }
      else if (tool === 'furniture-fridge') { kind = 'fridge'; size = [0.8, 0.7]; }
      else if (tool === 'furniture-sink') { kind = 'sink'; size = [0.9, 0.6]; }
      else if (tool === 'furniture-toilet') { kind = 'toilet'; size = [0.5, 0.7]; }
      else if (tool === 'furniture-bathtub') { kind = 'bathtub'; size = [1.7, 0.75]; }
      else if (tool === 'furniture-desk') { kind = 'desk'; size = [1.4, 0.7]; }
      else if (tool === 'furniture-office-chair') { kind = 'chair'; size = [0.6, 0.6]; }
      else if (tool === 'furniture-dining-table') { kind = 'dining'; size = [1.6, 0.9]; }
      else if (tool === 'structure-column') { kind = 'column'; size = [0.4, 0.4]; }
      else if (tool === 'stairs-straight') { kind = 'stairs'; size = [1.0, 2.5]; }
      else if (tool === 'stairs-l') { kind = 'stairs-l'; size = [2.0, 2.0]; }
      else if (tool === 'structure-railing') { kind = 'railing'; size = [2.0, 0.1]; }

      const newItem = {
        id: `f_${Date.now()}`,
        kind: kind,
        center: [pt.x, pt.y],
        size: size,
        angle: 0
      };

      this.sceneData.furniture.push(newItem);
      this.renderFurniture();
      this.updateEmptyState();
      this.selectEntity({ type: 'furniture', id: newItem.id, data: newItem });
    }

    updateStatus() {
      if (this.coordsLabel) {
        const x = this.currentMouse.snappedX.toFixed(2);
        const y = this.currentMouse.snappedY.toFixed(2);
        this.coordsLabel.textContent = `X: ${x >= 0 ? '+' : ''}${x} m   Y: ${y >= 0 ? '+' : ''}${y} m`;
      }
    }
  }

  // Safe Global Editor Instance
  function initEditorInstance() {
    if (!window.floorPlanEditor) {
      window.floorPlanEditor = new FloorPlanEditor();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEditorInstance);
  } else {
    initEditorInstance();
  }
})();
