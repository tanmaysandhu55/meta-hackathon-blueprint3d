/**
 * FloorPlan3D — 2D Floor Plan Editor (Part 1: Layout & Canvas)
 * Strict Editorial Studio Architecture & Native SVG Vector Canvas
 */

(function () {
    'use strict';

    const ADAPTIVE_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100];

    class FloorPlanEditor {
        constructor() {
            this.view = document.getElementById('editor-view');
            if (!this.view) return;

            // DOM References
            this.container = document.getElementById('editor-canvas-container');
            this.svg = document.getElementById('editor-svg-canvas');
            this.worldGroup = document.getElementById('editor-world-group');
            this.gridLayer = document.getElementById('editor-grid-layer');
            this.roomsLayer = document.getElementById('editor-rooms-layer');
            this.wallsLayer = document.getElementById('editor-walls-layer');
            this.openingsLayer = document.getElementById('editor-openings-layer');
            this.furnitureLayer = document.getElementById('editor-furniture-layer');
            this.previewLayer = document.getElementById('editor-draw-preview-layer');
            this.selectionLayer = document.getElementById('editor-selection-layer');

            this.screenOverlay = document.getElementById('editor-screen-overlay');
            this.rulersLayer = document.getElementById('editor-rulers-layer');
            this.labelsLayer = document.getElementById('editor-labels-layer');
            this.guidesLayer = document.getElementById('editor-guides-layer');

            // Scale Bar & Empty State
            this.scaleBar = document.getElementById('editor-scale-bar');
            this.scaleBarLine = document.getElementById('editor-scale-bar-line');
            this.scaleBarLabel = document.getElementById('editor-scale-bar-label');
            this.emptyState = document.getElementById('editor-empty-state');

            // Status Bar Elements
            this.statusCoords = document.getElementById('editor-status-coords');
            this.statusZoom = document.getElementById('editor-status-zoom');
            this.statusTool = document.getElementById('editor-status-tool');
            this.statusHint = document.getElementById('editor-status-hint');

            // Top Bar Controls
            this.planNameInput = document.getElementById('editor-plan-name');
            this.snapToggle = document.getElementById('editor-snap-toggle');
            this.snapStepSelect = document.getElementById('editor-snap-step');
            this.zoomDisplay = document.getElementById('editor-zoom-display');
            this.btnZoomIn = document.getElementById('btn-editor-zoom-in');
            this.btnZoomOut = document.getElementById('btn-editor-zoom-out');
            this.btnZoomFit = document.getElementById('btn-editor-zoom-fit');
            this.btnSendTo3D = document.getElementById('btn-editor-send-to-3d');
            this.btnBack = document.getElementById('btn-editor-back');
            this.btnUndo = document.getElementById('btn-editor-undo');
            this.btnRedo = document.getElementById('btn-editor-redo');

            // Tool rail
            this.toolButtons = document.querySelectorAll('.editor-tool-btn');

            // Empty state buttons
            this.btnEmptyDrawWalls = document.getElementById('btn-empty-draw-walls');
            this.btnEmptyLoadSample = document.getElementById('btn-empty-load-sample');
            this.btnEmptyLoadAi = document.getElementById('btn-empty-load-ai');

            // View Transformation State
            this.pan = { x: 0, y: 0 };
            this.zoom = 50; // px/m (clamped 10 to 400)
            this.activeTool = 'select';
            this.snapEnabled = true;
            this.snapStep = 0.25; // meters
            this.planName = 'Untitled Plan';

            // Pan and Interaction State
            this.isPanning = false;
            this.isSpacePressed = false;
            this.panStart = { x: 0, y: 0 };
            this.cursorWorld = { x: 0, y: 0 };

            // Scene Geometry Data (Reads/Writes scene.json schema)
            this.scene = {
                meta: {
                    name: 'Untitled Plan',
                    units: 'meters',
                    wallHeight: 3.0,
                    wallThickness: 0.2,
                    metersPerPixel: 1 / 50,
                    levels: 1
                },
                walls: [],
                rooms: [],
                doors: [],
                windows: [],
                furniture: []
            };

            // History Stacks
            this.undoStack = [];
            this.redoStack = [];

            // Bind Event Handlers
            this.initEvents();

            // Initial view setup
            this.initDefaultView();

            window.floorPlanEditor = this;
        }

        // --------------------------------------------------------------------------
        // Coordinate Transforms
        // --------------------------------------------------------------------------
        worldToScreen(wx, wy) {
            return {
                x: this.pan.x + wx * this.zoom,
                y: this.pan.y + wy * this.zoom
            };
        }

        screenToWorld(sx, sy) {
            return {
                x: (sx - this.pan.x) / this.zoom,
                y: (sy - this.pan.y) / this.zoom
            };
        }

        snapValue(val, step = this.snapStep) {
            return Math.round(val / step) * step;
        }

        snapPoint(wx, wy) {
            if (!this.snapEnabled) return { x: wx, y: wy };
            return {
                x: this.snapValue(wx),
                y: this.snapValue(wy)
            };
        }

        // --------------------------------------------------------------------------
        // Viewport Initialization & Sizing
        // --------------------------------------------------------------------------
        getContainerDims() {
            if (!this.container) return { width: 1000, height: 700 };
            const rect = this.container.getBoundingClientRect();
            return {
                width: rect.width || this.container.clientWidth || 1000,
                height: rect.height || this.container.clientHeight || 700
            };
        }

        initDefaultView() {
            const dims = this.getContainerDims();
            this.zoom = 50; // Initial 50 px/m
            // Center on 12m x 8m area (center is at x = 6.0, y = 4.0)
            this.pan.x = dims.width / 2 - 6.0 * this.zoom;
            this.pan.y = dims.height / 2 - 4.0 * this.zoom;
            this.render();
            this.updateStatus();
        }

        onShow() {
            // When editor view is made visible
            if (!this.hasObjects()) {
                this.initDefaultView();
            } else {
                this.fitToView();
            }
        }

        hasObjects() {
            return (
                (this.scene.walls && this.scene.walls.length > 0) ||
                (this.scene.rooms && this.scene.rooms.length > 0) ||
                (this.scene.doors && this.scene.doors.length > 0) ||
                (this.scene.windows && this.scene.windows.length > 0) ||
                (this.scene.furniture && this.scene.furniture.length > 0)
            );
        }

        fitToView() {
            const dims = this.getContainerDims();
            if (!this.hasObjects()) {
                // Reset to default 12m x 8m view
                this.zoom = 50;
                this.pan.x = dims.width / 2 - 6.0 * this.zoom;
                this.pan.y = dims.height / 2 - 4.0 * this.zoom;
                this.render();
                this.updateStatus();
                return;
            }

            // Compute bounding box of all objects
            let minX = Infinity, maxX = -Infinity;
            let minY = Infinity, maxY = -Infinity;

            const check = (x, y) => {
                if (Number.isFinite(x) && Number.isFinite(y)) {
                    minX = Math.min(minX, x);
                    maxX = Math.max(maxX, x);
                    minY = Math.min(minY, y);
                    maxY = Math.max(maxY, y);
                }
            };

            (this.scene.walls || []).forEach(w => {
                (w.polygon || []).forEach(pt => check(pt[0], pt[1]));
            });
            (this.scene.rooms || []).forEach(r => {
                (r.polygon || []).forEach(pt => check(pt[0], pt[1]));
            });
            (this.scene.doors || []).forEach(d => {
                if (d.center) check(d.center[0], d.center[1]);
            });
            (this.scene.windows || []).forEach(win => {
                if (win.center) check(win.center[0], win.center[1]);
            });
            (this.scene.furniture || []).forEach(f => {
                if (f.center) check(f.center[0], f.center[1]);
            });

            if (!Number.isFinite(minX)) {
                this.initDefaultView();
                return;
            }

            const w = Math.max(maxX - minX, 2) * 1.25; // 25% margin
            const h = Math.max(maxY - minY, 2) * 1.25;

            const fitZoom = Math.min((dims.width - 80) / w, (dims.height - 80) / h);
            this.zoom = Math.max(10, Math.min(400, fitZoom));

            const centerX = (minX + maxX) / 2;
            const centerY = (minY + maxY) / 2;
            this.pan.x = dims.width / 2 - centerX * this.zoom;
            this.pan.y = dims.height / 2 - centerY * this.zoom;

            this.render();
            this.updateStatus();
        }

        setZoom(newZoom, centerX, centerY) {
            const clamped = Math.max(10, Math.min(400, newZoom));
            if (clamped === this.zoom) return;

            const dims = this.getContainerDims();
            const cx = centerX !== undefined ? centerX : dims.width / 2;
            const cy = centerY !== undefined ? centerY : dims.height / 2;

            // Maintain world point under cursor / center
            const worldX = (cx - this.pan.x) / this.zoom;
            const worldY = (cy - this.pan.y) / this.zoom;

            this.zoom = clamped;
            this.pan.x = cx - worldX * this.zoom;
            this.pan.y = cy - worldY * this.zoom;

            this.render();
            this.updateStatus();
        }

        // --------------------------------------------------------------------------
        // Event Binding
        // --------------------------------------------------------------------------
        initEvents() {
            // Window resize
            window.addEventListener('resize', () => {
                if (this.view && !this.view.classList.contains('view-hidden')) {
                    this.render();
                }
            });

            // Keyboard navigation (Space for pan)
            window.addEventListener('keydown', (e) => {
                if (this.view && this.view.classList.contains('view-hidden')) return;

                if (e.code === 'Space' && !this.isSpacePressed && e.target.tagName !== 'INPUT') {
                    this.isSpacePressed = true;
                    if (this.container) this.container.style.cursor = 'grab';
                    e.preventDefault();
                }

                if (e.key === 'f' || e.key === 'F') {
                    if (e.target.tagName !== 'INPUT') {
                        this.fitToView();
                        e.preventDefault();
                    }
                }
            });

            window.addEventListener('keyup', (e) => {
                if (e.code === 'Space') {
                    this.isSpacePressed = false;
                    if (!this.isPanning && this.container) {
                        this.container.style.cursor = 'default';
                    }
                }
            });

            // Canvas Pointer Interaction (Pan & Zoom)
            if (this.container) {
                this.container.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
                this.container.addEventListener('pointerdown', (e) => this.onPointerDown(e));
                window.addEventListener('pointermove', (e) => this.onPointerMove(e));
                window.addEventListener('pointerup', (e) => this.onPointerUp(e));
            }

            // Top Bar Action Listeners
            this.btnZoomIn?.addEventListener('click', () => {
                this.setZoom(this.zoom * 1.25);
            });

            this.btnZoomOut?.addEventListener('click', () => {
                this.setZoom(this.zoom / 1.25);
            });

            this.btnZoomFit?.addEventListener('click', () => {
                this.fitToView();
            });

            this.snapToggle?.addEventListener('change', (e) => {
                this.snapEnabled = e.target.checked;
                this.render();
                this.updateStatus();
            });

            this.snapStepSelect?.addEventListener('change', (e) => {
                this.snapStep = parseFloat(e.target.value) || 0.25;
                this.render();
                this.updateStatus();
            });

            this.planNameInput?.addEventListener('input', (e) => {
                this.planName = e.target.value || 'Untitled Plan';
                this.scene.meta.name = this.planName;
            });

            // Tool rail click delegation
            this.toolButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    const tool = btn.dataset.tool;
                    if (tool) this.setActiveTool(tool);
                });
            });

            // Empty state buttons
            this.btnEmptyDrawWalls?.addEventListener('click', () => {
                this.setActiveTool('wall');
                if (this.emptyState) this.emptyState.classList.add('hidden');
            });

            this.btnEmptyLoadSample?.addEventListener('click', async () => {
                try {
                    const res = await fetch('/api/sample');
                    const data = await res.json();
                    if (data && data.scene) {
                        this.loadSceneData(data.scene);
                        this.fitToView();
                    }
                } catch (err) {
                    console.error('Failed to load sample:', err);
                }
            });

            this.btnEmptyLoadAi?.addEventListener('click', async () => {
                try {
                    if (window.viewer && window.viewer.currentSceneData) {
                        this.loadSceneData(window.viewer.currentSceneData);
                        this.fitToView();
                        return;
                    }
                    const res = await fetch('/api/sample');
                    const data = await res.json();
                    if (data && data.scene) {
                        this.loadSceneData(data.scene);
                        this.fitToView();
                    }
                } catch (err) {
                    console.error('Failed to load AI result:', err);
                }
            });

            // Back to Studio
            this.btnBack?.addEventListener('click', () => {
                if (window.FloorPlan3DStudio?.switchToLandingView) {
                    window.FloorPlan3DStudio.switchToLandingView();
                }
            });

            // Send to 3D View
            this.btnSendTo3D?.addEventListener('click', () => {
                this.sendTo3D();
            });
        }

        setActiveTool(tool) {
            this.activeTool = tool;
            this.toolButtons.forEach(btn => {
                if (btn.dataset.tool === tool) {
                    btn.classList.add('is-active');
                } else {
                    btn.classList.remove('is-active');
                }
            });
            this.updateStatus();
        }

        // --------------------------------------------------------------------------
        // Pan & Wheel Zoom Handlers
        // --------------------------------------------------------------------------
        onWheel(e) {
            e.preventDefault();
            const rect = this.container.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            // Factor: positive delta is scroll down (zoom out), negative is zoom in
            const factor = e.deltaY < 0 ? 1.15 : (1 / 1.15);
            this.setZoom(this.zoom * factor, mouseX, mouseY);
        }

        onPointerDown(e) {
            // Space + Left Click or Middle Mouse (button === 1) triggers Pan
            if (e.button === 1 || (e.button === 0 && this.isSpacePressed)) {
                this.isPanning = true;
                this.panStart = {
                    x: e.clientX - this.pan.x,
                    y: e.clientY - this.pan.y
                };
                if (this.container) this.container.style.cursor = 'grabbing';
                e.preventDefault();
                return;
            }
        }

        onPointerMove(e) {
            if (!this.container) return;
            const rect = this.container.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            this.cursorWorld = this.screenToWorld(mouseX, mouseY);
            this.updateCoordsDisplay();

            if (this.isPanning) {
                this.pan.x = e.clientX - this.panStart.x;
                this.pan.y = e.clientY - this.panStart.y;
                this.render();
            }
        }

        onPointerUp(e) {
            if (this.isPanning) {
                this.isPanning = false;
                if (this.container) {
                    this.container.style.cursor = this.isSpacePressed ? 'grab' : 'default';
                }
            }
        }

        // --------------------------------------------------------------------------
        // Adaptive Ruler & Metric Grid Rendering
        // --------------------------------------------------------------------------
        getAdaptiveRulerStep() {
            // Find smallest step from [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100] where step * zoom >= 80px
            for (const step of ADAPTIVE_STEPS) {
                if (step * this.zoom >= 80) {
                    return step;
                }
            }
            return 100;
        }

        renderGrid() {
            if (!this.gridLayer) return;
            const dims = this.getContainerDims();

            const topLeft = this.screenToWorld(0, 0);
            const bottomRight = this.screenToWorld(dims.width, dims.height);

            const minWX = Math.floor(Math.min(topLeft.x, bottomRight.x) / 5) * 5 - 10;
            const maxWX = Math.ceil(Math.max(topLeft.x, bottomRight.x) / 5) * 5 + 10;
            const minWY = Math.floor(Math.min(topLeft.y, bottomRight.y) / 5) * 5 - 10;
            const maxWY = Math.ceil(Math.max(topLeft.y, bottomRight.y) / 5) * 5 + 10;

            const minorStep = this.snapStep;
            const minorSpacingPx = minorStep * this.zoom;
            const showMinor = minorSpacingPx >= 6; // Fade grid lines that would be under 6px apart
            const showOneMeter = (1.0 * this.zoom) >= 6;

            let pathLines = '';

            // 1. Minor grid lines (if spacing >= 6px)
            if (showMinor && minorStep < 1.0) {
                let minorD = '';
                for (let x = minWX; x <= maxWX; x += minorStep) {
                    if (Math.abs(x % 1.0) < 0.001 || Math.abs(x % 5.0) < 0.001) continue;
                    minorD += `M ${x.toFixed(3)} ${minWY.toFixed(3)} V ${maxWY.toFixed(3)} `;
                }
                for (let y = minWY; y <= maxWY; y += minorStep) {
                    if (Math.abs(y % 1.0) < 0.001 || Math.abs(y % 5.0) < 0.001) continue;
                    minorD += `M ${minWX.toFixed(3)} ${y.toFixed(3)} H ${maxWX.toFixed(3)} `;
                }
                if (minorD) {
                    pathLines += `<path d="${minorD}" stroke="#EBE7DE" stroke-width="0.5" class="editor-grid-line" />`;
                }
            }

            // 2. 1-meter grid lines
            if (showOneMeter) {
                let oneMeterD = '';
                for (let x = Math.floor(minWX); x <= Math.ceil(maxWX); x += 1.0) {
                    if (Math.abs(x % 5.0) < 0.001) continue;
                    oneMeterD += `M ${x} ${minWY.toFixed(3)} V ${maxWY.toFixed(3)} `;
                }
                for (let y = Math.floor(minWY); y <= Math.ceil(maxWY); y += 1.0) {
                    if (Math.abs(y % 5.0) < 0.001) continue;
                    oneMeterD += `M ${minWX.toFixed(3)} ${y} H ${maxWX.toFixed(3)} `;
                }
                if (oneMeterD) {
                    pathLines += `<path d="${oneMeterD}" stroke="#DDD8CF" stroke-width="0.75" class="editor-grid-line" />`;
                }
            }

            // 3. 5-meter grid lines (ALWAYS show)
            let fiveMeterD = '';
            for (let x = Math.floor(minWX / 5) * 5; x <= Math.ceil(maxWX / 5) * 5; x += 5.0) {
                fiveMeterD += `M ${x} ${minWY.toFixed(3)} V ${maxWY.toFixed(3)} `;
            }
            for (let y = Math.floor(minWY / 5) * 5; y <= Math.ceil(maxWY / 5) * 5; y += 5.0) {
                fiveMeterD += `M ${minWX.toFixed(3)} ${y} H ${maxWX.toFixed(3)} `;
            }
            if (fiveMeterD) {
                pathLines += `<path d="${fiveMeterD}" stroke="#B8B0A2" stroke-width="1" class="editor-grid-line" />`;
            }

            // 4. Origin Axes (X = 0, Y = 0)
            const axesD = `M 0 ${minWY.toFixed(3)} V ${maxWY.toFixed(3)} M ${minWX.toFixed(3)} 0 H ${maxWX.toFixed(3)}`;
            pathLines += `<path d="${axesD}" stroke="#9B3418" stroke-width="1.25" opacity="0.6" class="editor-grid-line" />`;

            this.gridLayer.innerHTML = pathLines;
        }

        renderRulers() {
            if (!this.rulersLayer) return;
            const dims = this.getContainerDims();
            const rulerStep = this.getAdaptiveRulerStep();

            const topLeft = this.screenToWorld(0, 0);
            const bottomRight = this.screenToWorld(dims.width, dims.height);

            const minWX = Math.floor(topLeft.x / rulerStep) * rulerStep;
            const maxWX = Math.ceil(bottomRight.x / rulerStep) * rulerStep;
            const minWY = Math.floor(topLeft.y / rulerStep) * rulerStep;
            const maxWY = Math.ceil(bottomRight.y / rulerStep) * rulerStep;

            let html = '';

            // Ruler Background Strips (Top & Left)
            html += `<rect x="0" y="0" width="${dims.width}" height="20" fill="var(--ground, #E7E3DA)" opacity="0.95" />`;
            html += `<rect x="0" y="0" width="20" height="${dims.height}" fill="var(--ground, #E7E3DA)" opacity="0.95" />`;
            html += `<line x1="0" y1="20" x2="${dims.width}" y2="20" stroke="#B8B0A2" stroke-width="1" class="editor-ruler-base" />`;
            html += `<line x1="20" y1="0" x2="20" y2="${dims.height}" stroke="#B8B0A2" stroke-width="1" class="editor-ruler-base" />`;

            // Top-left origin badge
            html += `<rect x="0" y="0" width="20" height="20" fill="var(--ground-2, #DDD8CF)" stroke="#B8B0A2" stroke-width="1" class="editor-ruler-base" />`;
            html += `<text x="10" y="14" text-anchor="middle" font-family="'Azeret Mono', monospace" font-size="9" fill="var(--ink-2, #5F5C55)">m</text>`;

            // Horizontal Ruler (Top)
            for (let wx = minWX; wx <= maxWX; wx += rulerStep) {
                const sx = this.pan.x + wx * this.zoom;
                if (sx < 20 || sx > dims.width) continue;
                html += `<line x1="${sx.toFixed(1)}" y1="14" x2="${sx.toFixed(1)}" y2="20" stroke="#1F1E1B" stroke-width="1" class="editor-ruler-tick" />`;
                const label = Number(wx.toFixed(2));
                html += `<text x="${(sx + 3).toFixed(1)}" y="12" class="editor-ruler-text">${label}</text>`;
            }

            // Vertical Ruler (Left)
            for (let wy = minWY; wy <= maxWY; wy += rulerStep) {
                const sy = this.pan.y + wy * this.zoom;
                if (sy < 20 || sy > dims.height) continue;
                html += `<line x1="14" y1="${sy.toFixed(1)}" x2="20" y2="${sy.toFixed(1)}" stroke="#1F1E1B" stroke-width="1" class="editor-ruler-tick" />`;
                const label = Number(wy.toFixed(2));
                html += `<text x="3" y="${(sy + 12).toFixed(1)}" class="editor-ruler-text">${label}</text>`;
            }

            this.rulersLayer.innerHTML = html;
        }

        updateScaleBar() {
            if (!this.scaleBarLine || !this.scaleBarLabel) return;
            // Pick metric length: 1, 2, 5, or 10 meters so width in px is ~50-150px
            let lengthM = 1;
            if (this.zoom < 25) lengthM = 5;
            else if (this.zoom < 60) lengthM = 2;
            else lengthM = 1;

            const widthPx = lengthM * this.zoom;
            this.scaleBarLine.style.width = `${Math.round(widthPx)}px`;
            this.scaleBarLabel.textContent = `${lengthM} m`;
        }

        updateStatus() {
            if (this.zoomDisplay) {
                this.zoomDisplay.textContent = `${Math.round(this.zoom)} px/m`;
            }
            if (this.statusZoom) {
                const pct = Math.round((this.zoom / 50) * 100);
                this.statusZoom.textContent = `${Math.round(this.zoom)} px/m (${pct}%)`;
            }
            if (this.statusTool) {
                const cap = this.activeTool.charAt(0).toUpperCase() + this.activeTool.slice(1);
                this.statusTool.textContent = `Tool: ${cap}`;
            }
            this.updateScaleBar();
        }

        updateCoordsDisplay() {
            if (this.statusCoords) {
                const xStr = this.cursorWorld.x.toFixed(2);
                const yStr = this.cursorWorld.y.toFixed(2);
                this.statusCoords.textContent = `X: ${xStr} m  Y: ${yStr} m`;
            }
        }

        // --------------------------------------------------------------------------
        // Scene Render & Updates
        // --------------------------------------------------------------------------
        render() {
            // Apply pan and zoom transform to world group
            if (this.worldGroup) {
                this.worldGroup.setAttribute(
                    'transform',
                    `translate(${this.pan.x.toFixed(2)}, ${this.pan.y.toFixed(2)}) scale(${this.zoom.toFixed(5)})`
                );
            }

            // Render adaptive grid in world coordinates
            this.renderGrid();

            // Render adaptive perimeter rulers in screen space
            this.renderRulers();

            // Render geometry layers
            this.renderGeometryLayers();

            // Update scale bar
            this.updateScaleBar();

            // Toggle empty state card
            if (this.emptyState) {
                if (this.hasObjects()) {
                    this.emptyState.classList.add('hidden');
                } else {
                    this.emptyState.classList.remove('hidden');
                }
            }
        }

        renderGeometryLayers() {
            // Render basic existing geometry if any is loaded
            if (this.wallsLayer) {
                let wallsSvg = '';
                (this.scene.walls || []).forEach(w => {
                    const poly = w.polygon || [];
                    if (poly.length >= 2) {
                        const points = poly.map(p => `${p[0]},${p[1]}`).join(' ');
                        wallsSvg += `<polygon points="${points}" fill="#5F5C55" stroke="#1F1E1B" stroke-width="0.05" class="editor-outline" />`;
                    }
                });
                this.wallsLayer.innerHTML = wallsSvg;
            }

            if (this.roomsLayer) {
                let roomsSvg = '';
                (this.scene.rooms || []).forEach(r => {
                    const poly = r.polygon || [];
                    if (poly.length >= 3) {
                        const points = poly.map(p => `${p[0]},${p[1]}`).join(' ');
                        roomsSvg += `<polygon points="${points}" fill="#D9D4C7" fill-opacity="0.6" stroke="#9B3418" stroke-width="0.04" class="editor-outline" />`;
                    }
                });
                this.roomsLayer.innerHTML = roomsSvg;
            }

            // Render constant-screen-size room labels in screen overlay
            if (this.labelsLayer) {
                let labelsSvg = '';
                (this.scene.rooms || []).forEach(r => {
                    const poly = r.polygon || [];
                    if (poly.length >= 3) {
                        const cx = poly.reduce((s, p) => s + p[0], 0) / poly.length;
                        const cy = poly.reduce((s, p) => s + p[1], 0) / poly.length;
                        const screenPos = this.worldToScreen(cx, cy);
                        const labelText = r.label || r.id || 'Room';
                        labelsSvg += `<text x="${screenPos.x.toFixed(1)}" y="${screenPos.y.toFixed(1)}" text-anchor="middle" dominant-baseline="middle" class="editor-canvas-label editor-room-label">${labelText}</text>`;
                    }
                });
                this.labelsLayer.innerHTML = labelsSvg;
            }
        }

        // --------------------------------------------------------------------------
        // Data Bridge: scene.json Import & Export
        // --------------------------------------------------------------------------
        loadSceneData(data) {
            if (!data) return;
            this.scene = {
                meta: {
                    name: data.meta?.name || 'Imported Plan',
                    units: 'meters',
                    wallHeight: Number(data.meta?.wallHeight) || 3.0,
                    wallThickness: Number(data.meta?.wallThickness) || 0.2,
                    metersPerPixel: Number(data.meta?.metersPerPixel) || (1 / 50),
                    levels: Number(data.meta?.levels) || 1
                },
                walls: Array.isArray(data.walls) ? JSON.parse(JSON.stringify(data.walls)) : [],
                rooms: Array.isArray(data.rooms) ? JSON.parse(JSON.stringify(data.rooms)) : [],
                doors: Array.isArray(data.doors) ? JSON.parse(JSON.stringify(data.doors)) : [],
                windows: Array.isArray(data.windows) ? JSON.parse(JSON.stringify(data.windows)) : [],
                furniture: Array.isArray(data.furniture) ? JSON.parse(JSON.stringify(data.furniture)) : []
            };

            this.planName = this.scene.meta.name;
            if (this.planNameInput) this.planNameInput.value = this.planName;

            this.render();
            this.updateStatus();
        }

        exportSceneData() {
            return {
                meta: {
                    name: this.planName || 'Untitled Plan',
                    units: 'meters',
                    wallHeight: Number(this.scene.meta?.wallHeight) || 3.0,
                    wallThickness: Number(this.scene.meta?.wallThickness) || 0.2,
                    metersPerPixel: 1 / 50,
                    levels: Number(this.scene.meta?.levels) || 1
                },
                walls: this.scene.walls || [],
                rooms: this.scene.rooms || [],
                doors: this.scene.doors || [],
                windows: this.scene.windows || [],
                furniture: this.scene.furniture || []
            };
        }

        sendTo3D() {
            const sceneData = this.exportSceneData();
            if (window.FloorPlan3DStudio?.switchToAppView) {
                window.FloorPlan3DStudio.switchToAppView();
            }
            if (window.viewer && typeof window.viewer.loadScene === 'function') {
                window.viewer.loadScene(sceneData);
            }
        }
    }

    // Auto-instantiate when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => new FloorPlanEditor());
    } else {
        new FloorPlanEditor();
    }

})();
