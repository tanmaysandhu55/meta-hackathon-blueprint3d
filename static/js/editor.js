/**
 * FloorPlan3D — 2D Floor Plan Editor
 * Strict Editorial Studio Architecture & Native SVG Vector Canvas
 * Parts 1, 2 & 3: Layout, Drawing, Selection, Object Library & 3D Bridge
 */

(function () {
    'use strict';

    const ADAPTIVE_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100];

    // Standard Library Catalog Definitions
    const LIBRARY_DEFS = {
        'wall.exterior': {
            id: 'wall.exterior',
            category: 'structure',
            name: 'Ext Wall',
            tool: 'wall',
            thickness: 0.20,
            wallType: 'exterior'
        },
        'wall.interior': {
            id: 'wall.interior',
            category: 'structure',
            name: 'Int Wall',
            tool: 'wall',
            thickness: 0.12,
            wallType: 'interior'
        },
        'struct.railing': {
            id: 'struct.railing',
            category: 'structure',
            name: 'Railing',
            tool: 'wall',
            thickness: 0.08,
            wallType: 'railing'
        },
        'struct.column': {
            id: 'struct.column',
            category: 'structure',
            name: 'Column',
            tool: 'furniture',
            width: 0.40,
            depth: 0.40
        },
        'struct.stairs_l': {
            id: 'struct.stairs_l',
            category: 'structure',
            name: 'Stairs L',
            tool: 'furniture',
            width: 2.40,
            depth: 2.40
        },
        'struct.stairs': {
            id: 'struct.stairs',
            category: 'structure',
            name: 'Stairs',
            tool: 'furniture',
            width: 1.10,
            depth: 2.60
        },

        'door.single': {
            id: 'door.single',
            category: 'doors',
            name: 'Single',
            tool: 'door',
            width: 0.90,
            doorType: 'single'
        },
        'door.double': {
            id: 'door.double',
            category: 'doors',
            name: 'Double',
            tool: 'door',
            width: 1.60,
            doorType: 'double'
        },
        'door.sliding': {
            id: 'door.sliding',
            category: 'doors',
            name: 'Sliding',
            tool: 'door',
            width: 1.50,
            doorType: 'sliding'
        },

        'window.single': {
            id: 'window.single',
            category: 'windows',
            name: 'Single',
            tool: 'window',
            width: 0.90,
            windowType: 'single'
        },
        'window.double': {
            id: 'window.double',
            category: 'windows',
            name: 'Double',
            tool: 'window',
            width: 1.40,
            windowType: 'double'
        },
        'window.wide': {
            id: 'window.wide',
            category: 'windows',
            name: 'Wide',
            tool: 'window',
            width: 2.20,
            windowType: 'wide'
        },

        'furn.bed': {
            id: 'furn.bed',
            category: 'furniture',
            name: 'Bed',
            tool: 'furniture',
            width: 2.00,
            depth: 1.60
        },
        'furn.sofa': {
            id: 'furn.sofa',
            category: 'furniture',
            name: 'Sofa',
            tool: 'furniture',
            width: 2.20,
            depth: 0.90
        },
        'furn.table_coffee': {
            id: 'furn.table_coffee',
            category: 'furniture',
            name: 'Table',
            tool: 'furniture',
            width: 1.20,
            depth: 0.60
        },
        'furn.chairs': {
            id: 'furn.chairs',
            category: 'furniture',
            name: 'Chairs',
            tool: 'furniture',
            width: 1.80,
            depth: 1.40
        },

        'furn.sink': {
            id: 'furn.sink',
            category: 'furniture',
            name: 'Sink',
            tool: 'furniture',
            width: 1.20,
            depth: 0.60
        },
        'furn.toilet': {
            id: 'furn.toilet',
            category: 'furniture',
            name: 'Toilet',
            tool: 'furniture',
            width: 0.50,
            depth: 0.70
        },
        'furn.bathtub': {
            id: 'furn.bathtub',
            category: 'furniture',
            name: 'Tub',
            tool: 'furniture',
            width: 1.70,
            depth: 0.80
        },
        'furn.stove': {
            id: 'furn.stove',
            category: 'furniture',
            name: 'Stove',
            tool: 'furniture',
            width: 0.80,
            depth: 0.70
        },
        'furn.fridge': {
            id: 'furn.fridge',
            category: 'furniture',
            name: 'Fridge',
            tool: 'furniture',
            width: 0.90,
            depth: 0.80
        },

        'furn.desk': {
            id: 'furn.desk',
            category: 'furniture',
            name: 'Desk',
            tool: 'furniture',
            width: 1.40,
            depth: 0.70
        },
        'furn.office_chair': {
            id: 'furn.office_chair',
            category: 'furniture',
            name: 'Office Chair',
            tool: 'furniture',
            width: 0.65,
            depth: 0.65
        },
        'furn.dining_table': {
            id: 'furn.dining_table',
            category: 'furniture',
            name: 'Dining',
            tool: 'furniture',
            width: 1.80,
            depth: 0.90
        },

        'text.label': {
            id: 'text.label',
            category: 'text',
            name: 'Label',
            tool: 'text'
        },
        'text.dimension': {
            id: 'text.dimension',
            category: 'text',
            name: 'Dimension',
            tool: 'dimension'
        }
    };

    function uid(prefix = 'item_') {
        return prefix + Math.random().toString(36).substr(2, 7);
    }

    // Shoelace area formula
    function computeShoelaceArea(polygon) {
        if (!polygon || polygon.length < 3) return 0;
        let area = 0;
        const n = polygon.length;
        for (let i = 0; i < n; i++) {
            const j = (i + 1) % n;
            area += polygon[i][0] * polygon[j][1];
            area -= polygon[j][0] * polygon[i][1];
        }
        return Math.abs(area) / 2.0;
    }

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

            // Panels
            this.libraryPanel = document.getElementById('editor-library-panel');
            this.propertiesPanel = document.getElementById('editor-properties-panel');
            this.propertiesContent = document.getElementById('editor-prop-content');
            this.btnToggleLibrary = document.getElementById('btn-toggle-library');
            this.btnCloseProperties = document.getElementById('btn-close-properties');

            // Room Dialog Dialog
            this.roomDialog = document.getElementById('editor-room-dialog');
            this.roomNameInput = document.getElementById('editor-room-name-input');
            this.roomTypeSelect = document.getElementById('editor-room-type-select');
            this.btnSaveRoom = document.getElementById('btn-save-room');
            this.btnCancelRoom = document.getElementById('btn-cancel-room');

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
            this.libCells = document.querySelectorAll('.editor-lib-cell');

            // Empty state buttons
            this.btnEmptyDrawWalls = document.getElementById('btn-empty-draw-walls');
            this.btnEmptyLoadSample = document.getElementById('btn-empty-load-sample');
            this.btnEmptyLoadAi = document.getElementById('btn-empty-load-ai');

            // View Transformation State
            this.pan = { x: 0, y: 0 };
            this.zoom = 50; // px/m
            this.activeTool = 'select';
            this.armedLibItem = null;
            this.snapEnabled = true;
            this.snapStep = 0.25; // meters
            this.planName = 'Untitled Plan';

            // Interaction State
            this.isPanning = false;
            this.isSpacePressed = false;
            this.isShiftPressed = false;
            this.panStart = { x: 0, y: 0 };
            this.cursorWorld = { x: 0, y: 0 };

            // Active Drawing States
            this.drawingWall = null; // { points: [{x, y}], type: 'exterior' | 'interior', thickness: 0.20 }
            this.drawingRoomPoints = []; // [{x, y}]
            this.pendingClosedRoom = null; // points awaiting dialog save
            this.typedLengthBuffer = '';

            // Selection State
            this.selectedObjects = []; // [{ type: 'wall' | 'room' | 'door' | 'window' | 'furniture', id }]
            this.isDraggingObject = false;
            this.dragStartWorld = { x: 0, y: 0 };
            this.isRotating = false;
            this.rotateCenter = { x: 0, y: 0 };
            this.isRubberBanding = false;
            this.rubberBandStart = { x: 0, y: 0 };
            this.rubberBandEnd = { x: 0, y: 0 };

            // Scene Geometry Data (Reads/Writes scene.json schema)
            this.scene = {
                meta: {
                    name: 'Untitled Plan',
                    units: 'meters',
                    wallHeight: 3.0,
                    wallThickness: 0.2,
                    metersPerPixel: 1 / 50,
                    levelCount: 1,
                    levels: [{ level: 0, floorIndex: 0, name: 'Ground Floor', elevation: 0 }]
                },
                walls: [],
                rooms: [],
                doors: [],
                windows: [],
                furniture: []
            };

            // History Stacks (50 steps max)
            this.undoStack = [];
            this.redoStack = [];

            // Initialize Event Listeners & Canvas
            this.initEvents();
            this.initDefaultView();

            window.floorPlanEditor = this;
        }

        // --------------------------------------------------------------------------
        // Coordinate Transforms & Snapping
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
            if (!this.snapEnabled) return { x: wx, y: wy, isSnappedToPoint: false };

            // First check snapping to existing wall/room endpoints within threshold
            const snapThreshold = 0.35; // meters
            let nearestDist = snapThreshold;
            let nearestPt = null;

            const checkPoint = (px, py) => {
                const dist = Math.hypot(px - wx, py - wy);
                if (dist < nearestDist) {
                    nearestDist = dist;
                    nearestPt = { x: px, y: py };
                }
            };

            // Existing wall endpoints
            (this.scene.walls || []).forEach(w => {
                if (w.p1) checkPoint(w.p1[0], w.p1[1]);
                if (w.p2) checkPoint(w.p2[0], w.p2[1]);
                (w.polygon || []).forEach(pt => checkPoint(pt[0], pt[1]));
            });

            // Room vertices
            (this.scene.rooms || []).forEach(r => {
                (r.polygon || []).forEach(pt => checkPoint(pt[0], pt[1]));
            });

            // Current wall drawing start point
            if (this.drawingWall && this.drawingWall.points.length > 0) {
                const p0 = this.drawingWall.points[0];
                checkPoint(p0.x, p0.y);
            }

            // Current room drawing start point
            if (this.drawingRoomPoints.length > 0) {
                const p0 = this.drawingRoomPoints[0];
                checkPoint(p0.x, p0.y);
            }

            if (nearestPt) {
                return { x: nearestPt.x, y: nearestPt.y, isSnappedToPoint: true };
            }

            // Otherwise snap to grid
            return {
                x: this.snapValue(wx),
                y: this.snapValue(wy),
                isSnappedToPoint: false
            };
        }

        // Find nearest wall centerline within distance (for doors/windows)
        findNearestWall(wx, wy, maxDist = 0.60) {
            let bestWall = null;
            let minDist = maxDist;
            let bestProj = null;
            let bestAngle = 0;

            (this.scene.walls || []).forEach(w => {
                let p1 = w.p1, p2 = w.p2;
                if (!p1 || !p2) {
                    if (w.polygon && w.polygon.length >= 4) {
                        p1 = [(w.polygon[0][0] + w.polygon[3][0]) / 2, (w.polygon[0][1] + w.polygon[3][1]) / 2];
                        p2 = [(w.polygon[1][0] + w.polygon[2][0]) / 2, (w.polygon[1][1] + w.polygon[2][1]) / 2];
                    }
                }
                if (!p1 || !p2) return;

                const dx = p2[0] - p1[0];
                const dy = p2[1] - p1[1];
                const lenSq = dx * dx + dy * dy;
                if (lenSq < 0.001) return;

                // Projection parameter t
                let t = ((wx - p1[0]) * dx + (wy - p1[1]) * dy) / lenSq;
                t = Math.max(0, Math.min(1, t));

                const projX = p1[0] + t * dx;
                const projY = p1[1] + t * dy;
                const dist = Math.hypot(wx - projX, wy - projY);

                if (dist < minDist) {
                    minDist = dist;
                    bestWall = w;
                    bestProj = [projX, projY];
                    bestAngle = Math.atan2(dy, dx);
                }
            });

            return bestWall ? { wall: bestWall, point: bestProj, angle: bestAngle } : null;
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
                this.initDefaultView();
                return;
            }

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

            const w = Math.max(maxX - minX, 2) * 1.25;
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

            const worldX = (cx - this.pan.x) / this.zoom;
            const worldY = (cy - this.pan.y) / this.zoom;

            this.zoom = clamped;
            this.pan.x = cx - worldX * this.zoom;
            this.pan.y = cy - worldY * this.zoom;

            this.render();
            this.updateStatus();
        }

        // --------------------------------------------------------------------------
        // History & Undo/Redo Engine (Deep Snapshot, 50 Steps)
        // --------------------------------------------------------------------------
        pushHistory() {
            const snapshot = JSON.stringify(this.scene);
            this.undoStack.push(snapshot);
            if (this.undoStack.length > 50) this.undoStack.shift();
            this.redoStack = []; // Reset redo stack on new action
            this.updateUndoRedoButtons();
        }

        undo() {
            if (this.undoStack.length === 0) return;
            const current = JSON.stringify(this.scene);
            this.redoStack.push(current);
            const prev = this.undoStack.pop();
            this.scene = JSON.parse(prev);
            this.selectedObjects = [];
            this.updatePropertiesPanel();
            this.render();
            this.updateUndoRedoButtons();
        }

        redo() {
            if (this.redoStack.length === 0) return;
            const current = JSON.stringify(this.scene);
            this.undoStack.push(current);
            const next = this.redoStack.pop();
            this.scene = JSON.parse(next);
            this.selectedObjects = [];
            this.updatePropertiesPanel();
            this.render();
            this.updateUndoRedoButtons();
        }

        updateUndoRedoButtons() {
            if (this.btnUndo) this.btnUndo.disabled = (this.undoStack.length === 0);
            if (this.btnRedo) this.btnRedo.disabled = (this.redoStack.length === 0);
        }

        // --------------------------------------------------------------------------
        // Event Binding
        // --------------------------------------------------------------------------
        initEvents() {
            window.addEventListener('resize', () => {
                if (this.view && !this.view.classList.contains('view-hidden')) {
                    this.render();
                }
            });

            // Keyboard Shortcuts
            window.addEventListener('keydown', (e) => {
                if (this.view && this.view.classList.contains('view-hidden')) return;

                if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
                    if (e.key === 'Escape') e.target.blur();
                    return;
                }

                // Space for pan
                if (e.code === 'Space' && !this.isSpacePressed) {
                    this.isSpacePressed = true;
                    if (this.container) this.container.style.cursor = 'grab';
                    e.preventDefault();
                }

                if (e.key === 'Shift') {
                    this.isShiftPressed = true;
                }

                // Undo / Redo
                if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
                    if (e.shiftKey) this.redo();
                    else this.undo();
                    e.preventDefault();
                    return;
                }
                if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) {
                    this.redo();
                    e.preventDefault();
                    return;
                }

                // Duplicate (Ctrl+D)
                if ((e.ctrlKey || e.metaKey) && (e.key === 'd' || e.key === 'D')) {
                    this.duplicateSelected();
                    e.preventDefault();
                    return;
                }

                // Delete / Backspace
                if (e.key === 'Delete' || e.key === 'Backspace') {
                    this.deleteSelected();
                    e.preventDefault();
                    return;
                }

                // Fit view (F)
                if (e.key === 'f' || e.key === 'F') {
                    this.fitToView();
                    e.preventDefault();
                    return;
                }

                // Escape: Disarm or cancel current drawing
                if (e.key === 'Escape') {
                    this.cancelCurrentGesture();
                    e.preventDefault();
                    return;
                }

                // Enter: Finish wall chain or commit typed length
                if (e.key === 'Enter') {
                    if (this.drawingWall) {
                        if (this.typedLengthBuffer) {
                            this.commitTypedLength();
                        } else {
                            this.finishDrawingWall();
                        }
                    }
                    e.preventDefault();
                    return;
                }

                // Arrow keys: Nudge selected objects
                if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                    this.nudgeSelected(e.key);
                    e.preventDefault();
                    return;
                }

                // Numbers typed while drawing wall
                if (this.drawingWall && (/[0-9.]/).test(e.key)) {
                    this.typedLengthBuffer += e.key;
                    this.updateDrawingPreview();
                }

                // Quick Tool Shortcuts
                if (!e.ctrlKey && !e.metaKey) {
                    if (e.key === 'v' || e.key === 'V') this.setActiveTool('select');
                    if (e.key === 'w' || e.key === 'W') this.armLibraryItem('wall.exterior');
                    if (e.key === 'r' || e.key === 'R') this.setActiveTool('room');
                    if (e.key === 'd' || e.key === 'D') this.armLibraryItem('door.single');
                }
            });

            window.addEventListener('keyup', (e) => {
                if (e.code === 'Space') {
                    this.isSpacePressed = false;
                    if (!this.isPanning && this.container) {
                        this.container.style.cursor = 'default';
                    }
                }
                if (e.key === 'Shift') {
                    this.isShiftPressed = false;
                }
            });

            // Canvas Pointer Events
            if (this.container) {
                this.container.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
                this.container.addEventListener('pointerdown', (e) => this.onPointerDown(e));
                window.addEventListener('pointermove', (e) => this.onPointerMove(e));
                window.addEventListener('pointerup', (e) => this.onPointerUp(e));
                this.container.addEventListener('dblclick', (e) => this.onDoubleClick(e));
            }

            // Top Bar Action Listeners
            this.btnZoomIn?.addEventListener('click', () => this.setZoom(this.zoom * 1.25));
            this.btnZoomOut?.addEventListener('click', () => this.setZoom(this.zoom / 1.25));
            this.btnZoomFit?.addEventListener('click', () => this.fitToView());
            this.btnUndo?.addEventListener('click', () => this.undo());
            this.btnRedo?.addEventListener('click', () => this.redo());

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

            // Tool Rail Handlers
            this.toolButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    const tool = btn.dataset.tool;
                    if (tool === 'library') {
                        this.toggleLibraryPanel();
                    } else if (tool) {
                        this.setActiveTool(tool);
                    }
                });
            });

            // Library Accordion Toggle Delegation
            document.querySelectorAll('.editor-accordion-header').forEach(header => {
                header.addEventListener('click', () => {
                    const expanded = header.getAttribute('aria-expanded') === 'true';
                    header.setAttribute('aria-expanded', String(!expanded));
                });
            });

            // Delegated Click for Object Library Cells
            this.libraryPanel?.addEventListener('click', (e) => {
                const cell = e.target.closest('.editor-lib-cell');
                if (!cell) return;
                const libId = cell.dataset.libId;
                if (libId) {
                    this.armLibraryItem(libId);
                }
            });

            this.btnToggleLibrary?.addEventListener('click', () => {
                this.toggleLibraryPanel();
            });

            this.btnCloseProperties?.addEventListener('click', () => {
                this.selectedObjects = [];
                this.updatePropertiesPanel();
                this.render();
            });

            // Room Dialog Handlers
            this.btnSaveRoom?.addEventListener('click', () => this.saveRoomFromDialog());
            this.btnCancelRoom?.addEventListener('click', () => this.cancelRoomDialog());

            // Empty state buttons
            this.btnEmptyDrawWalls?.addEventListener('click', () => {
                this.armLibraryItem('wall.exterior');
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
                    const v = window.floorPlanViewer || window.viewer;
                    if (v && v.currentSceneData) {
                        this.loadSceneData(v.currentSceneData);
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

        toggleLibraryPanel(forceState) {
            const isCollapsed = this.view.classList.contains('is-library-collapsed');
            const shouldCollapse = forceState !== undefined ? !forceState : !isCollapsed;
            if (shouldCollapse) {
                this.view.classList.add('is-library-collapsed');
                document.getElementById('btn-rail-library')?.classList.remove('is-active');
            } else {
                this.view.classList.remove('is-library-collapsed');
                document.getElementById('btn-rail-library')?.classList.add('is-active');
            }
        }

        // --------------------------------------------------------------------------
        // Active Tool & Library Arming
        // --------------------------------------------------------------------------
        setActiveTool(tool) {
            this.activeTool = tool;
            this.armedLibItem = null;
            this.typedLengthBuffer = '';

            // Update Tool Rail buttons
            this.toolButtons.forEach(btn => {
                if (btn.dataset.tool === tool) {
                    btn.classList.add('is-active');
                } else if (btn.dataset.tool !== 'library') {
                    btn.classList.remove('is-active');
                }
            });

            // Clear armed states on library cells
            this.libCells.forEach(cell => cell.classList.remove('is-active', 'is-armed'));

            if (tool === 'delete') {
                if (this.container) this.container.style.cursor = 'crosshair';
            } else if (tool === 'select') {
                if (this.container) this.container.style.cursor = 'default';
            } else {
                if (this.container) this.container.style.cursor = 'crosshair';
            }

            this.updateStatus();
        }

        armLibraryItem(libId) {
            const def = LIBRARY_DEFS[libId];
            if (!def) return;

            this.armedLibItem = def;
            this.activeTool = def.tool;

            // Highlight corresponding cell in Library
            this.libCells.forEach(cell => {
                if (cell.dataset.libId === libId) {
                    cell.classList.add('is-armed');
                } else {
                    cell.classList.remove('is-armed');
                }
            });

            // Update rail button
            this.toolButtons.forEach(btn => {
                if (btn.dataset.tool === def.tool) {
                    btn.classList.add('is-active');
                } else if (btn.dataset.tool !== 'library') {
                    btn.classList.remove('is-active');
                }
            });

            if (this.container) this.container.style.cursor = 'crosshair';
            this.updateStatus();
        }

        cancelCurrentGesture() {
            if (this.drawingWall) {
                this.drawingWall = null;
                this.previewLayer.innerHTML = '';
                this.labelsLayer.innerHTML = '';
            }
            if (this.drawingRoomPoints.length > 0) {
                this.drawingRoomPoints = [];
                this.previewLayer.innerHTML = '';
                this.labelsLayer.innerHTML = '';
            }
            if (this.armedLibItem) {
                this.setActiveTool('select');
            }
            this.render();
            this.updateStatus();
        }

        // --------------------------------------------------------------------------
        // Pointer Handlers: Pan, Zoom, Draw & Select
        // --------------------------------------------------------------------------
        onWheel(e) {
            e.preventDefault();
            const rect = this.container.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            const factor = e.deltaY < 0 ? 1.15 : (1 / 1.15);
            this.setZoom(this.zoom * factor, mouseX, mouseY);
        }

        onPointerDown(e) {
            // Space + Left Click or Middle Mouse triggers Pan
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

            if (e.button !== 0) return; // Only process left click for interactions

            const rect = this.container.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;
            const rawWorld = this.screenToWorld(mouseX, mouseY);
            const snapped = this.snapPoint(rawWorld.x, rawWorld.y);

            // 1. Delete Tool: Click to delete
            if (this.activeTool === 'delete') {
                const clickedObj = this.getObjectUnderScreen(mouseX, mouseY);
                if (clickedObj) {
                    this.deleteObject(clickedObj);
                }
                return;
            }

            // 2. Select Tool: Selection & Dragging
            if (this.activeTool === 'select') {
                const clickedObj = this.getObjectUnderScreen(mouseX, mouseY);
                if (clickedObj) {
                    if (this.isShiftPressed) {
                        // Multi-select toggle
                        const idx = this.selectedObjects.findIndex(o => o.id === clickedObj.id);
                        if (idx >= 0) this.selectedObjects.splice(idx, 1);
                        else this.selectedObjects.push(clickedObj);
                    } else {
                        // Single select
                        this.selectedObjects = [clickedObj];
                    }
                    this.isDraggingObject = true;
                    this.dragStartWorld = { x: rawWorld.x, y: rawWorld.y };
                    this.updatePropertiesPanel();
                    this.render();
                } else {
                    // Click on empty ground
                    if (!this.isShiftPressed) {
                        this.selectedObjects = [];
                        this.updatePropertiesPanel();
                    }
                    // Start rubber band selection
                    this.isRubberBanding = true;
                    this.rubberBandStart = { x: mouseX, y: mouseY };
                    this.rubberBandEnd = { x: mouseX, y: mouseY };
                    this.render();
                }
                return;
            }

            // 3. Wall Tool: Click to start or add wall vertex
            if (this.activeTool === 'wall') {
                const wallType = this.armedLibItem?.wallType || 'exterior';
                const thickness = this.armedLibItem?.thickness || (wallType === 'exterior' ? 0.20 : 0.12);

                if (!this.drawingWall) {
                    // Start new wall chain
                    this.drawingWall = {
                        points: [{ x: snapped.x, y: snapped.y }],
                        type: wallType,
                        thickness: thickness
                    };
                    if (this.emptyState) this.emptyState.classList.add('hidden');
                } else {
                    // Add vertex and commit wall segment
                    const lastPt = this.drawingWall.points[this.drawingWall.points.length - 1];
                    if (Math.hypot(snapped.x - lastPt.x, snapped.y - lastPt.y) > 0.05) {
                        this.addWallSegment(lastPt, snapped, this.drawingWall.type, this.drawingWall.thickness);
                        this.drawingWall.points.push({ x: snapped.x, y: snapped.y });
                    }
                }
                this.typedLengthBuffer = '';
                this.render();
                return;
            }

            // 4. Room Tool: Trace room polygon
            if (this.activeTool === 'room') {
                if (this.drawingRoomPoints.length === 0) {
                    this.drawingRoomPoints.push({ x: snapped.x, y: snapped.y });
                    if (this.emptyState) this.emptyState.classList.add('hidden');
                } else {
                    const p0 = this.drawingRoomPoints[0];
                    // Check if clicked close to start point (closing loop)
                    if (this.drawingRoomPoints.length >= 3 && Math.hypot(snapped.x - p0.x, snapped.y - p0.y) <= 0.45) {
                        this.promptCreateRoom(this.drawingRoomPoints);
                        this.drawingRoomPoints = [];
                    } else {
                        this.drawingRoomPoints.push({ x: snapped.x, y: snapped.y });
                    }
                }
                this.render();
                return;
            }

            // 5. Door Tool: Snap onto wall
            if (this.activeTool === 'door') {
                const nearest = this.findNearestWall(rawWorld.x, rawWorld.y, 0.70);
                if (nearest) {
                    const width = this.armedLibItem?.width || 0.90;
                    const door = {
                        id: uid('door_'),
                        wallId: nearest.wall.id,
                        center: [nearest.point[0], nearest.point[1]],
                        width: width,
                        angle: nearest.angle,
                        type: this.armedLibItem?.doorType || 'single',
                        flip: false
                    };
                    this.pushHistory();
                    this.scene.doors.push(door);
                    if (!this.isShiftPressed) this.setActiveTool('select');
                    this.render();
                }
                return;
            }

            // 6. Window Tool: Snap onto wall
            if (this.activeTool === 'window') {
                const nearest = this.findNearestWall(rawWorld.x, rawWorld.y, 0.70);
                if (nearest) {
                    const width = this.armedLibItem?.width || 1.20;
                    const win = {
                        id: uid('win_'),
                        wallId: nearest.wall.id,
                        center: [nearest.point[0], nearest.point[1]],
                        width: width,
                        angle: nearest.angle,
                        type: this.armedLibItem?.windowType || 'double'
                    };
                    this.pushHistory();
                    this.scene.windows.push(win);
                    if (!this.isShiftPressed) this.setActiveTool('select');
                    this.render();
                }
                return;
            }

            // 7. Furniture Placement: Place at snapped coordinates
            if (this.activeTool === 'furniture') {
                if (this.armedLibItem) {
                    const width = this.armedLibItem.width || 1.5;
                    const depth = this.armedLibItem.depth || 0.8;
                    const furn = {
                        id: uid('furn_'),
                        type: this.armedLibItem.id,
                        name: this.armedLibItem.name,
                        center: [snapped.x, snapped.y],
                        width: width,
                        depth: depth,
                        angle: 0
                    };
                    this.pushHistory();
                    this.scene.furniture.push(furn);
                    if (!this.isShiftPressed) this.setActiveTool('select');
                    this.render();
                }
                return;
            }

            // 8. Text Placement
            if (this.activeTool === 'text') {
                const labelText = prompt("Enter text label:", "Label");
                if (labelText) {
                    this.pushHistory();
                    this.scene.rooms.push({
                        id: uid('label_'),
                        label: labelText,
                        type: 'label',
                        polygon: [
                            [snapped.x - 0.5, snapped.y - 0.3],
                            [snapped.x + 0.5, snapped.y - 0.3],
                            [snapped.x + 0.5, snapped.y + 0.3],
                            [snapped.x - 0.5, snapped.y + 0.3]
                        ]
                    });
                    this.setActiveTool('select');
                    this.render();
                }
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

            // Panning
            if (this.isPanning) {
                this.pan.x = e.clientX - this.panStart.x;
                this.pan.y = e.clientY - this.panStart.y;
                this.render();
                return;
            }

            // Dragging selected objects
            if (this.isDraggingObject && this.selectedObjects.length > 0) {
                const deltaX = this.cursorWorld.x - this.dragStartWorld.x;
                const deltaY = this.cursorWorld.y - this.dragStartWorld.y;
                const snapDx = this.snapValue(deltaX);
                const snapDy = this.snapValue(deltaY);

                if (Math.abs(snapDx) > 0 || Math.abs(snapDy) > 0) {
                    this.moveSelected(snapDx, snapDy);
                    this.dragStartWorld.x += snapDx;
                    this.dragStartWorld.y += snapDy;
                    this.render();
                }
                return;
            }

            // Rubber band dragging
            if (this.isRubberBanding) {
                this.rubberBandEnd = { x: mouseX, y: mouseY };
                this.updateRubberBand();
                return;
            }

            // Live preview updates while drawing or hovering
            this.updateDrawingPreview();
        }

        onPointerUp(e) {
            if (this.isPanning) {
                this.isPanning = false;
                if (this.container) {
                    this.container.style.cursor = this.isSpacePressed ? 'grab' : 'default';
                }
            }

            if (this.isDraggingObject) {
                this.isDraggingObject = false;
                this.pushHistory();
            }

            if (this.isRubberBanding) {
                this.isRubberBanding = false;
                this.commitRubberBand();
                this.render();
            }
        }

        onDoubleClick(e) {
            if (this.drawingWall) {
                this.finishDrawingWall();
                e.preventDefault();
            }
        }

        // --------------------------------------------------------------------------
        // Geometry Creation & Manipulation
        // --------------------------------------------------------------------------
        addWallSegment(p1, p2, type = 'exterior', thickness = 0.20) {
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const len = Math.hypot(dx, dy);
            if (len < 0.05) return;

            // Perpendicular unit normal
            const nx = -dy / len;
            const ny = dx / len;
            const ht = thickness / 2;

            // 4-vertex wall polygon
            const poly = [
                [Number((p1.x + nx * ht).toFixed(3)), Number((p1.y + ny * ht).toFixed(3))],
                [Number((p2.x + nx * ht).toFixed(3)), Number((p2.y + ny * ht).toFixed(3))],
                [Number((p2.x - nx * ht).toFixed(3)), Number((p2.y - ny * ht).toFixed(3))],
                [Number((p1.x - nx * ht).toFixed(3)), Number((p1.y - ny * ht).toFixed(3))]
            ];

            const wall = {
                id: uid('wall_'),
                type: type,
                thickness: thickness,
                p1: [p1.x, p1.y],
                p2: [p2.x, p2.y],
                polygon: poly
            };

            this.pushHistory();
            this.scene.walls.push(wall);
            this.render();
        }

        finishDrawingWall() {
            this.drawingWall = null;
            this.typedLengthBuffer = '';
            this.previewLayer.innerHTML = '';
            this.labelsLayer.innerHTML = '';
            this.render();
        }

        commitTypedLength() {
            const targetLen = parseFloat(this.typedLengthBuffer);
            if (!Number.isFinite(targetLen) || targetLen <= 0 || !this.drawingWall) {
                this.typedLengthBuffer = '';
                return;
            }

            const points = this.drawingWall.points;
            const lastPt = points[points.length - 1];
            const dx = this.cursorWorld.x - lastPt.x;
            const dy = this.cursorWorld.y - lastPt.y;
            const curDist = Math.hypot(dx, dy) || 1;
            const angle = Math.atan2(dy, dx);

            const nextPt = {
                x: Number((lastPt.x + Math.cos(angle) * targetLen).toFixed(3)),
                y: Number((lastPt.y + Math.sin(angle) * targetLen).toFixed(3))
            };

            this.addWallSegment(lastPt, nextPt, this.drawingWall.type, this.drawingWall.thickness);
            this.drawingWall.points.push(nextPt);
            this.typedLengthBuffer = '';
            this.render();
        }

        promptCreateRoom(points) {
            this.pendingClosedRoom = points.map(p => [p.x, p.y]);
            if (this.roomDialog) {
                this.roomDialog.classList.remove('is-hidden');
                if (this.roomNameInput) {
                    this.roomNameInput.value = `Room ${this.scene.rooms.length + 1}`;
                    this.roomNameInput.focus();
                }
            }
        }

        saveRoomFromDialog() {
            if (!this.pendingClosedRoom) return;
            const name = this.roomNameInput?.value.trim() || 'Room';
            const type = this.roomTypeSelect?.value || 'living';

            const room = {
                id: uid('room_'),
                label: name,
                type: type,
                polygon: this.pendingClosedRoom
            };

            this.pushHistory();
            this.scene.rooms.push(room);
            this.pendingClosedRoom = null;
            if (this.roomDialog) this.roomDialog.classList.add('is-hidden');
            this.render();
        }

        cancelRoomDialog() {
            this.pendingClosedRoom = null;
            if (this.roomDialog) this.roomDialog.classList.add('is-hidden');
            this.render();
        }

        // Selection & Movement
        getObjectUnderScreen(sx, sy) {
            const world = this.screenToWorld(sx, sy);
            const radius = 12 / this.zoom; // 12px hit radius in world units

            // 1. Check Furniture
            for (const f of this.scene.furniture || []) {
                if (Math.hypot(f.center[0] - world.x, f.center[1] - world.y) <= Math.max(f.width, f.depth) / 1.5) {
                    return { type: 'furniture', id: f.id, item: f };
                }
            }

            // 2. Check Doors
            for (const d of this.scene.doors || []) {
                if (Math.hypot(d.center[0] - world.x, d.center[1] - world.y) <= radius * 1.5) {
                    return { type: 'door', id: d.id, item: d };
                }
            }

            // 3. Check Windows
            for (const w of this.scene.windows || []) {
                if (Math.hypot(w.center[0] - world.x, w.center[1] - world.y) <= radius * 1.5) {
                    return { type: 'window', id: w.id, item: w };
                }
            }

            // 4. Check Walls
            for (const wall of this.scene.walls || []) {
                if (wall.p1 && wall.p2) {
                    const dist = this.distToSegment(world.x, world.y, wall.p1[0], wall.p1[1], wall.p2[0], wall.p2[1]);
                    if (dist <= (wall.thickness || 0.2) / 2 + radius) {
                        return { type: 'wall', id: wall.id, item: wall };
                    }
                }
            }

            // 5. Check Rooms
            for (const r of this.scene.rooms || []) {
                if (this.pointInPolygon(world.x, world.y, r.polygon || [])) {
                    return { type: 'room', id: r.id, item: r };
                }
            }

            return null;
        }

        distToSegment(px, py, x1, y1, x2, y2) {
            const dx = x2 - x1, dy = y2 - y1;
            const lenSq = dx * dx + dy * dy;
            if (lenSq === 0) return Math.hypot(px - x1, py - y1);
            let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
            t = Math.max(0, Math.min(1, t));
            return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
        }

        pointInPolygon(x, y, vs) {
            let inside = false;
            for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
                const xi = vs[i][0], yi = vs[i][1];
                const xj = vs[j][0], yj = vs[j][1];
                const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
                if (intersect) inside = !inside;
            }
            return inside;
        }

        moveSelected(dx, dy) {
            this.selectedObjects.forEach(sel => {
                if (sel.type === 'furniture' && sel.item) {
                    sel.item.center[0] += dx;
                    sel.item.center[1] += dy;
                } else if (sel.type === 'door' && sel.item) {
                    sel.item.center[0] += dx;
                    sel.item.center[1] += dy;
                } else if (sel.type === 'window' && sel.item) {
                    sel.item.center[0] += dx;
                    sel.item.center[1] += dy;
                } else if (sel.type === 'wall' && sel.item) {
                    if (sel.item.p1) { sel.item.p1[0] += dx; sel.item.p1[1] += dy; }
                    if (sel.item.p2) { sel.item.p2[0] += dx; sel.item.p2[1] += dy; }
                    (sel.item.polygon || []).forEach(p => { p[0] += dx; p[1] += dy; });
                } else if (sel.type === 'room' && sel.item) {
                    (sel.item.polygon || []).forEach(p => { p[0] += dx; p[1] += dy; });
                }
            });
        }

        nudgeSelected(key) {
            if (this.selectedObjects.length === 0) return;
            const step = this.snapStep;
            let dx = 0, dy = 0;
            if (key === 'ArrowUp') dy = -step;
            if (key === 'ArrowDown') dy = step;
            if (key === 'ArrowLeft') dx = -step;
            if (key === 'ArrowRight') dx = step;

            this.moveSelected(dx, dy);
            this.pushHistory();
            this.render();
        }

        deleteSelected() {
            if (this.selectedObjects.length === 0) return;
            this.pushHistory();
            this.selectedObjects.forEach(sel => {
                this.deleteObject(sel);
            });
            this.selectedObjects = [];
            this.updatePropertiesPanel();
            this.render();
        }

        deleteObject(obj) {
            if (obj.type === 'wall') {
                this.scene.walls = this.scene.walls.filter(w => w.id !== obj.id);
            } else if (obj.type === 'room') {
                this.scene.rooms = this.scene.rooms.filter(r => r.id !== obj.id);
            } else if (obj.type === 'door') {
                this.scene.doors = this.scene.doors.filter(d => d.id !== obj.id);
            } else if (obj.type === 'window') {
                this.scene.windows = this.scene.windows.filter(win => win.id !== obj.id);
            } else if (obj.type === 'furniture') {
                this.scene.furniture = this.scene.furniture.filter(f => f.id !== obj.id);
            }
        }

        duplicateSelected() {
            if (this.selectedObjects.length === 0) return;
            this.pushHistory();
            const newSelections = [];

            this.selectedObjects.forEach(sel => {
                if (sel.type === 'furniture' && sel.item) {
                    const copy = JSON.parse(JSON.stringify(sel.item));
                    copy.id = uid('furn_');
                    copy.center[0] += 0.5;
                    copy.center[1] += 0.5;
                    this.scene.furniture.push(copy);
                    newSelections.push({ type: 'furniture', id: copy.id, item: copy });
                } else if (sel.type === 'wall' && sel.item) {
                    const copy = JSON.parse(JSON.stringify(sel.item));
                    copy.id = uid('wall_');
                    copy.p1[0] += 0.5; copy.p1[1] += 0.5;
                    copy.p2[0] += 0.5; copy.p2[1] += 0.5;
                    copy.polygon.forEach(p => { p[0] += 0.5; p[1] += 0.5; });
                    this.scene.walls.push(copy);
                    newSelections.push({ type: 'wall', id: copy.id, item: copy });
                }
            });

            this.selectedObjects = newSelections;
            this.updatePropertiesPanel();
            this.render();
        }

        updateRubberBand() {
            if (!this.selectionLayer) return;
            const x1 = Math.min(this.rubberBandStart.x, this.rubberBandEnd.x);
            const y1 = Math.min(this.rubberBandStart.y, this.rubberBandEnd.y);
            const w = Math.abs(this.rubberBandEnd.x - this.rubberBandStart.x);
            const h = Math.abs(this.rubberBandEnd.y - this.rubberBandStart.y);

            const p1 = this.screenToWorld(x1, y1);
            const p2 = this.screenToWorld(x1 + w, y1 + h);

            this.selectionLayer.innerHTML = `
                <rect x="${p1.x}" y="${p1.y}" width="${p2.x - p1.x}" height="${p2.y - p1.y}" class="editor-selection-rect" />
            `;
        }

        commitRubberBand() {
            const x1 = Math.min(this.rubberBandStart.x, this.rubberBandEnd.x);
            const y1 = Math.min(this.rubberBandStart.y, this.rubberBandEnd.y);
            const w = Math.abs(this.rubberBandEnd.x - this.rubberBandStart.x);
            const h = Math.abs(this.rubberBandEnd.y - this.rubberBandStart.y);

            const p1 = this.screenToWorld(x1, y1);
            const p2 = this.screenToWorld(x1 + w, y1 + h);

            this.selectedObjects = [];
            (this.scene.furniture || []).forEach(f => {
                if (f.center[0] >= p1.x && f.center[0] <= p2.x && f.center[1] >= p1.y && f.center[1] <= p2.y) {
                    this.selectedObjects.push({ type: 'furniture', id: f.id, item: f });
                }
            });

            this.updatePropertiesPanel();
        }

        // --------------------------------------------------------------------------
        // Live Previews & Overlays
        // --------------------------------------------------------------------------
        updateDrawingPreview() {
            if (!this.previewLayer || !this.guidesLayer) return;
            const snapped = this.snapPoint(this.cursorWorld.x, this.cursorWorld.y);

            // 1. Guides: Snap Marker (8px square)
            if (snapped.isSnappedToPoint) {
                const screenPos = this.worldToScreen(snapped.x, snapped.y);
                this.guidesLayer.innerHTML = `
                    <rect x="${screenPos.x - 4}" y="${screenPos.y - 4}" width="8" height="8" class="editor-snap-marker" />
                `;
            } else {
                this.guidesLayer.innerHTML = '';
            }

            // 2. Wall Drawing Preview
            if (this.drawingWall && this.drawingWall.points.length > 0) {
                const lastPt = this.drawingWall.points[this.drawingWall.points.length - 1];
                const dx = snapped.x - lastPt.x;
                const dy = snapped.y - lastPt.y;
                const len = Math.hypot(dx, dy);

                const lineSvg = `<line x1="${lastPt.x}" y1="${lastPt.y}" x2="${snapped.x}" y2="${snapped.y}" class="editor-preview-line" />`;
                this.previewLayer.innerHTML = lineSvg;

                // Dimension text at center of segment in Screen Overlay
                const midX = (lastPt.x + snapped.x) / 2;
                const midY = (lastPt.y + snapped.y) / 2;
                const screenMid = this.worldToScreen(midX, midY);
                const displayLen = this.typedLengthBuffer ? `${this.typedLengthBuffer} m` : `${len.toFixed(2)} m`;

                this.labelsLayer.innerHTML = `
                    <text x="${screenMid.x}" y="${screenMid.y - 12}" text-anchor="middle" class="editor-canvas-label editor-length-label">${displayLen}</text>
                `;
                return;
            }

            // 3. Room Drawing Preview
            if (this.drawingRoomPoints.length > 0) {
                const pointsStr = this.drawingRoomPoints.map(p => `${p.x},${p.y}`).join(' ') + ` ${snapped.x},${snapped.y}`;
                this.previewLayer.innerHTML = `<polyline points="${pointsStr}" fill="none" class="editor-preview-line" />`;
                return;
            }

            // 4. Armed Furniture / Door / Window Ghost Preview
            if (this.activeTool === 'furniture' && this.armedLibItem) {
                const w = this.armedLibItem.width || 1.5;
                const d = this.armedLibItem.depth || 0.8;
                this.previewLayer.innerHTML = `
                    <g transform="translate(${snapped.x}, ${snapped.y})" class="editor-ghost">
                        <rect x="${-w / 2}" y="${-d / 2}" width="${w}" height="${d}" fill="var(--ground-2, #DDD8CF)" stroke="var(--pigment, #9B3418)" stroke-width="0.04" />
                        <text x="0" y="0" text-anchor="middle" dominant-baseline="middle" font-size="0.25" font-family="'Azeret Mono', monospace" fill="var(--pigment, #9B3418)">${this.armedLibItem.name}</text>
                    </g>
                `;
                return;
            }

            if (this.activeTool === 'door' || this.activeTool === 'window') {
                const nearest = this.findNearestWall(this.cursorWorld.x, this.cursorWorld.y, 0.70);
                if (nearest) {
                    const deg = (nearest.angle * 180) / Math.PI;
                    const w = this.activeTool === 'door' ? (this.armedLibItem?.width || 0.9) : (this.armedLibItem?.width || 1.2);
                    this.previewLayer.innerHTML = `
                        <g transform="translate(${nearest.point[0]}, ${nearest.point[1]}) rotate(${deg})" class="editor-ghost">
                            <rect x="${-w / 2}" y="-0.1" width="${w}" height="0.2" fill="var(--ground-2, #DDD8CF)" stroke="var(--pigment, #9B3418)" stroke-width="0.03" />
                        </g>
                    `;
                    return;
                }
            }

            this.previewLayer.innerHTML = '';
        }

        // --------------------------------------------------------------------------
        // Adaptive Ruler & Metric Grid Rendering
        // --------------------------------------------------------------------------
        getAdaptiveRulerStep() {
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
            const showMinor = minorSpacingPx >= 6;
            const showOneMeter = (1.0 * this.zoom) >= 6;

            let pathLines = '';

            // 1. Minor grid lines
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

            // 3. 5-meter grid lines (Always show)
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

            // 4. Origin Axes
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

            // Ruler Background Strips
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
                const toolName = this.armedLibItem ? this.armedLibItem.name : this.activeTool;
                const cap = toolName.charAt(0).toUpperCase() + toolName.slice(1);
                this.statusTool.textContent = `Tool: ${cap}`;
            }
            if (this.statusHint) {
                if (this.activeTool === 'wall') {
                    this.statusHint.textContent = "Click to set points · Enter or DblClick to finish · Type number to set length · Esc to cancel";
                } else if (this.activeTool === 'room') {
                    this.statusHint.textContent = "Click to trace perimeter · Click starting point to close room · Esc to cancel";
                } else if (this.activeTool === 'door' || this.activeTool === 'window') {
                    this.statusHint.textContent = "Hover near any wall to snap · Click to place opening · Hold Shift to place multiple";
                } else if (this.activeTool === 'furniture') {
                    this.statusHint.textContent = "Click to place item · Hold Shift to place multiple · Esc to cancel";
                } else {
                    this.statusHint.textContent = "Space+Drag to Pan · Wheel to Zoom · Click to Select · Del to remove · Ctrl+D to duplicate";
                }
            }
            this.updateScaleBar();
            this.updateUndoRedoButtons();
        }

        updateCoordsDisplay() {
            if (this.statusCoords) {
                const xStr = this.cursorWorld.x.toFixed(2);
                const yStr = this.cursorWorld.y.toFixed(2);
                this.statusCoords.textContent = `X: ${xStr} m  Y: ${yStr} m`;
            }
        }

        // --------------------------------------------------------------------------
        // Properties Panel Two-Way Data Binding
        // --------------------------------------------------------------------------
        updatePropertiesPanel() {
            if (!this.propertiesPanel || !this.propertiesContent) return;

            if (this.selectedObjects.length === 0) {
                this.propertiesPanel.classList.add('is-hidden');
                this.view.classList.remove('has-props-open');
                this.propertiesContent.innerHTML = '';
                return;
            }

            this.propertiesPanel.classList.remove('is-hidden');
            this.view.classList.add('has-props-open');

            const primary = this.selectedObjects[0];
            let html = '';

            if (primary.type === 'wall' && primary.item) {
                const w = primary.item;
                const p1 = w.p1 || [0, 0];
                const p2 = w.p2 || [1, 0];
                const len = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);

                html = `
                    <h4 class="prop-section-title">Wall Segment</h4>
                    <div class="prop-field-group">
                        <span class="prop-field-label">Type</span>
                        <div class="flex gap-2">
                            <button type="button" class="editor-prop-btn flex-1 ${w.type === 'exterior' ? 'bg-stone-300 font-bold' : ''}" id="btn-prop-wall-ext">Exterior</button>
                            <button type="button" class="editor-prop-btn flex-1 ${w.type === 'interior' ? 'bg-stone-300 font-bold' : ''}" id="btn-prop-wall-int">Interior</button>
                        </div>
                    </div>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Length (meters)</label>
                        <input type="number" step="0.05" value="${len.toFixed(2)}" class="editor-number-input" id="prop-wall-len" />
                    </div>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Thickness (meters)</label>
                        <input type="number" step="0.02" value="${(w.thickness || 0.20).toFixed(2)}" class="editor-number-input" id="prop-wall-thick" />
                    </div>
                    <div class="mt-4">
                        <button type="button" class="editor-prop-btn editor-prop-btn-danger w-full" id="btn-prop-delete">Delete Wall</button>
                    </div>
                `;
            } else if (primary.type === 'room' && primary.item) {
                const r = primary.item;
                const area = computeShoelaceArea(r.polygon || []);
                const areaSqFt = area * 10.7639;

                html = `
                    <h4 class="prop-section-title">Room Boundary</h4>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Room Name</label>
                        <input type="text" value="${r.label || 'Room'}" class="editor-text-input" id="prop-room-name" />
                    </div>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Classification</label>
                        <select class="editor-select" id="prop-room-type">
                            ${['living', 'bedroom', 'kitchen', 'dining', 'bathroom', 'office', 'classroom', 'lab', 'corridor', 'stairs', 'entrance', 'other'].map(t =>
                                `<option value="${t}" ${r.type === t ? 'selected' : ''}>${t.charAt(0).toUpperCase() + t.slice(1)}</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div class="prop-field-group p-3 bg-stone-200">
                        <span class="prop-field-label">Calculated Area</span>
                        <div class="font-serif text-lg font-medium">${area.toFixed(2)} m²</div>
                        <div class="mono-label text-[10px] text-stone-500">${areaSqFt.toFixed(1)} sq ft · ${r.polygon?.length || 0} vertices</div>
                    </div>
                    <div class="mt-4">
                        <button type="button" class="editor-prop-btn editor-prop-btn-danger w-full" id="btn-prop-delete">Delete Room</button>
                    </div>
                `;
            } else if (primary.type === 'door' && primary.item) {
                const d = primary.item;
                html = `
                    <h4 class="prop-section-title">Door Opening</h4>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Width</label>
                        <select class="editor-select" id="prop-door-width">
                            ${[0.60, 0.72, 0.80, 0.90, 1.00, 1.20, 1.60].map(w =>
                                `<option value="${w}" ${Math.abs(d.width - w) < 0.05 ? 'selected' : ''}>${w.toFixed(2)} m</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div class="prop-field-group mt-2">
                        <button type="button" class="editor-prop-btn w-full" id="btn-prop-door-flip">Flip Swing Direction</button>
                    </div>
                    <div class="mt-4">
                        <button type="button" class="editor-prop-btn editor-prop-btn-danger w-full" id="btn-prop-delete">Delete Door</button>
                    </div>
                `;
            } else if (primary.type === 'window' && primary.item) {
                const win = primary.item;
                html = `
                    <h4 class="prop-section-title">Window Opening</h4>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Width</label>
                        <select class="editor-select" id="prop-win-width">
                            ${[0.60, 0.90, 1.20, 1.40, 1.80, 2.20].map(w =>
                                `<option value="${w}" ${Math.abs(win.width - w) < 0.05 ? 'selected' : ''}>${w.toFixed(2)} m</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div class="mt-4">
                        <button type="button" class="editor-prop-btn editor-prop-btn-danger w-full" id="btn-prop-delete">Delete Window</button>
                    </div>
                `;
            } else if (primary.type === 'furniture' && primary.item) {
                const f = primary.item;
                const deg = Math.round(((f.angle || 0) * 180) / Math.PI) % 360;
                html = `
                    <h4 class="prop-section-title">${f.name || 'Furniture Item'}</h4>
                    <div class="prop-row">
                        <div class="prop-field-group flex-1">
                            <label class="prop-field-label">Width (m)</label>
                            <input type="number" step="0.1" value="${f.width.toFixed(2)}" class="editor-number-input" id="prop-furn-w" />
                        </div>
                        <div class="prop-field-group flex-1">
                            <label class="prop-field-label">Depth (m)</label>
                            <input type="number" step="0.1" value="${f.depth.toFixed(2)}" class="editor-number-input" id="prop-furn-d" />
                        </div>
                    </div>
                    <div class="prop-field-group">
                        <label class="prop-field-label">Rotation: ${deg}°</label>
                        <button type="button" class="editor-prop-btn w-full" id="btn-prop-furn-rotate">Rotate 90°</button>
                    </div>
                    <div class="mt-4">
                        <button type="button" class="editor-prop-btn editor-prop-btn-danger w-full" id="btn-prop-delete">Delete Item</button>
                    </div>
                `;
            }

            this.propertiesContent.innerHTML = html;

            // Wire property change listeners
            document.getElementById('btn-prop-delete')?.addEventListener('click', () => this.deleteSelected());

            document.getElementById('prop-room-name')?.addEventListener('input', (e) => {
                primary.item.label = e.target.value;
                this.render();
            });

            document.getElementById('prop-room-type')?.addEventListener('change', (e) => {
                this.pushHistory();
                primary.item.type = e.target.value;
                this.render();
            });

            document.getElementById('btn-prop-wall-ext')?.addEventListener('click', () => {
                this.pushHistory();
                primary.item.type = 'exterior';
                primary.item.thickness = 0.20;
                this.updatePropertiesPanel();
                this.render();
            });

            document.getElementById('btn-prop-wall-int')?.addEventListener('click', () => {
                this.pushHistory();
                primary.item.type = 'interior';
                primary.item.thickness = 0.12;
                this.updatePropertiesPanel();
                this.render();
            });

            document.getElementById('prop-wall-thick')?.addEventListener('change', (e) => {
                const val = parseFloat(e.target.value);
                if (val > 0) {
                    this.pushHistory();
                    primary.item.thickness = val;
                    this.render();
                }
            });

            document.getElementById('prop-door-width')?.addEventListener('change', (e) => {
                this.pushHistory();
                primary.item.width = parseFloat(e.target.value);
                this.render();
            });

            document.getElementById('btn-prop-door-flip')?.addEventListener('click', () => {
                this.pushHistory();
                primary.item.flip = !primary.item.flip;
                this.render();
            });

            document.getElementById('prop-win-width')?.addEventListener('change', (e) => {
                this.pushHistory();
                primary.item.width = parseFloat(e.target.value);
                this.render();
            });

            document.getElementById('prop-furn-w')?.addEventListener('change', (e) => {
                this.pushHistory();
                primary.item.width = parseFloat(e.target.value);
                this.render();
            });

            document.getElementById('prop-furn-d')?.addEventListener('change', (e) => {
                this.pushHistory();
                primary.item.depth = parseFloat(e.target.value);
                this.render();
            });

            document.getElementById('btn-prop-furn-rotate')?.addEventListener('click', () => {
                this.pushHistory();
                primary.item.angle = ((primary.item.angle || 0) + Math.PI / 2) % (Math.PI * 2);
                this.updatePropertiesPanel();
                this.render();
            });
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
                if (this.hasObjects() || this.drawingWall || this.drawingRoomPoints.length > 0) {
                    this.emptyState.classList.add('hidden');
                } else {
                    this.emptyState.classList.remove('hidden');
                }
            }
        }

        renderGeometryLayers() {
            // 1. Rooms Layer
            if (this.roomsLayer) {
                let roomsSvg = '';
                (this.scene.rooms || []).forEach(r => {
                    const poly = r.polygon || [];
                    if (poly.length >= 3) {
                        const isSel = this.selectedObjects.some(s => s.id === r.id);
                        const points = poly.map(p => `${p[0]},${p[1]}`).join(' ');
                        roomsSvg += `<polygon points="${points}" class="editor-room-polygon ${isSel ? 'is-selected' : ''}" />`;
                        // Invisible hit area
                        roomsSvg += `<polygon points="${points}" class="editor-hit-area" data-id="${r.id}" />`;
                    }
                });
                this.roomsLayer.innerHTML = roomsSvg;
            }

            // 2. Walls Layer
            if (this.wallsLayer) {
                let wallsSvg = '';
                (this.scene.walls || []).forEach(w => {
                    const poly = w.polygon || [];
                    const isSel = this.selectedObjects.some(s => s.id === w.id);
                    if (poly.length >= 2) {
                        const points = poly.map(p => `${p[0]},${p[1]}`).join(' ');
                        wallsSvg += `<polygon points="${points}" class="editor-wall-body ${isSel ? 'is-selected' : ''}" />`;
                    }
                    if (w.p1 && w.p2) {
                        wallsSvg += `<line x1="${w.p1[0]}" y1="${w.p1[1]}" x2="${w.p2[0]}" y2="${w.p2[1]}" class="editor-hit-area" data-id="${w.id}" />`;
                    }
                });
                this.wallsLayer.innerHTML = wallsSvg;
            }

            // 3. Openings Layer (Doors & Windows)
            if (this.openingsLayer) {
                let openingsSvg = '';
                // Doors
                (this.scene.doors || []).forEach(d => {
                    const isSel = this.selectedObjects.some(s => s.id === d.id);
                    const deg = ((d.angle || 0) * 180) / Math.PI;
                    const w = d.width || 0.9;
                    const r = w * 0.9;
                    const sweep = d.flip ? 0 : 1;

                    openingsSvg += `
                        <g transform="translate(${d.center[0]}, ${d.center[1]}) rotate(${deg})" class="editor-door-symbol ${isSel ? 'is-selected' : ''}">
                            <!-- Wall Cutout -->
                            <rect x="${-w / 2}" y="-0.12" width="${w}" height="0.24" fill="var(--ground, #E7E3DA)" stroke="none" />
                            <line x1="${-w / 2}" y1="-0.12" x2="${-w / 2}" y2="0.12" stroke="#1F1E1B" stroke-width="0.04" />
                            <line x1="${w / 2}" y1="-0.12" x2="${w / 2}" y2="0.12" stroke="#1F1E1B" stroke-width="0.04" />
                            <!-- Door Leaf & Swing Arc -->
                            <line x1="${-w / 2}" y1="0" x2="${-w / 2}" y2="${-w}" stroke="#1F1E1B" stroke-width="0.04" />
                            <path d="M ${-w / 2} ${-w} A ${r} ${r} 0 0 ${sweep} ${w / 2} 0" fill="none" stroke="#5F5C55" stroke-width="0.02" stroke-dasharray="0.05 0.05" />
                            <!-- Hit area -->
                            <rect x="${-w / 2}" y="${-w}" width="${w}" height="${w * 1.5}" class="editor-hit-area" data-id="${d.id}" />
                        </g>
                    `;
                });

                // Windows
                (this.scene.windows || []).forEach(win => {
                    const isSel = this.selectedObjects.some(s => s.id === win.id);
                    const deg = ((win.angle || 0) * 180) / Math.PI;
                    const w = win.width || 1.2;

                    openingsSvg += `
                        <g transform="translate(${win.center[0]}, ${win.center[1]}) rotate(${deg})" class="editor-window-symbol ${isSel ? 'is-selected' : ''}">
                            <!-- Cutout & double glass pane -->
                            <rect x="${-w / 2}" y="-0.10" width="${w}" height="0.20" fill="var(--ground, #E7E3DA)" stroke="none" />
                            <line x1="${-w / 2}" y1="-0.04" x2="${w / 2}" y2="-0.04" stroke="#1F1E1B" stroke-width="0.025" />
                            <line x1="${-w / 2}" y1="0.04" x2="${w / 2}" y2="0.04" stroke="#1F1E1B" stroke-width="0.025" />
                            <line x1="${-w / 2}" y1="-0.10" x2="${-w / 2}" y2="0.10" stroke="#1F1E1B" stroke-width="0.04" />
                            <line x1="${w / 2}" y1="-0.10" x2="${w / 2}" y2="0.10" stroke="#1F1E1B" stroke-width="0.04" />
                            <!-- Hit area -->
                            <rect x="${-w / 2}" y="-0.2" width="${w}" height="0.4" class="editor-hit-area" data-id="${win.id}" />
                        </g>
                    `;
                });

                this.openingsLayer.innerHTML = openingsSvg;
            }

            // 4. Furniture Layer
            if (this.furnitureLayer) {
                let furnSvg = '';
                (this.scene.furniture || []).forEach(f => {
                    const isSel = this.selectedObjects.some(s => s.id === f.id);
                    const deg = ((f.angle || 0) * 180) / Math.PI;
                    const w = f.width || 1.4;
                    const d = f.depth || 0.8;

                    furnSvg += `
                        <g transform="translate(${f.center[0]}, ${f.center[1]}) rotate(${deg})" class="editor-furniture-symbol ${isSel ? 'is-selected' : ''}">
                            <rect x="${-w / 2}" y="${-d / 2}" width="${w}" height="${d}" fill="#DDD8CF" stroke="#1F1E1B" stroke-width="0.03" />
                            <text x="0" y="0" text-anchor="middle" dominant-baseline="middle" font-size="${Math.min(w, d) * 0.25}" font-family="'Azeret Mono', monospace" fill="#5F5C55">${f.name || ''}</text>
                            <rect x="${-w / 2}" y="${-d / 2}" width="${w}" height="${d}" class="editor-hit-area" data-id="${f.id}" />
                        </g>
                    `;
                });
                this.furnitureLayer.innerHTML = furnSvg;
            }

            // 5. Selection Handles in Selection Layer
            if (this.selectionLayer) {
                let selSvg = '';
                this.selectedObjects.forEach(sel => {
                    if (sel.type === 'furniture' && sel.item) {
                        const f = sel.item;
                        const deg = ((f.angle || 0) * 180) / Math.PI;
                        const w = f.width || 1.4;
                        const d = f.depth || 0.8;
                        const hw = w / 2, hd = d / 2;

                        selSvg += `
                            <g transform="translate(${f.center[0]}, ${f.center[1]}) rotate(${deg})">
                                <rect x="${-hw}" y="${-hd}" width="${w}" height="${d}" fill="none" stroke="var(--pigment, #9B3418)" stroke-width="0.04" />
                                <rect x="${-hw - 0.08}" y="${-hd - 0.08}" width="0.16" height="0.16" class="editor-handle" />
                                <rect x="${hw - 0.08}" y="${-hd - 0.08}" width="0.16" height="0.16" class="editor-handle" />
                                <rect x="${hw - 0.08}" y="${hd - 0.08}" width="0.16" height="0.16" class="editor-handle" />
                                <rect x="${-hw - 0.08}" y="${hd - 0.08}" width="0.16" height="0.16" class="editor-handle" />
                                <!-- Rotation Handle -->
                                <line x1="0" y1="${-hd}" x2="0" y2="${-hd - 0.4}" stroke="var(--pigment, #9B3418)" stroke-width="0.03" />
                                <circle cx="0" cy="${-hd - 0.4}" r="0.08" class="editor-rotate-handle" />
                            </g>
                        `;
                    }
                });
                this.selectionLayer.innerHTML = selSvg;
            }

            // 6. Constant-Screen-Size Room Badges in Screen Overlay
            if (this.labelsLayer && !this.drawingWall) {
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
                    levelCount: Number(data.meta?.levelCount) || (Array.isArray(data.meta?.levels) ? data.meta.levels.length : 1),
                    levels: Array.isArray(data.meta?.levels) ? data.meta.levels : [{ level: 0, floorIndex: 0, name: 'Ground Floor', elevation: 0 }]
                },
                walls: Array.isArray(data.walls) ? JSON.parse(JSON.stringify(data.walls)) : [],
                rooms: Array.isArray(data.rooms) ? JSON.parse(JSON.stringify(data.rooms)) : [],
                doors: Array.isArray(data.doors) ? JSON.parse(JSON.stringify(data.doors)) : [],
                windows: Array.isArray(data.windows) ? JSON.parse(JSON.stringify(data.windows)) : [],
                furniture: Array.isArray(data.furniture) ? JSON.parse(JSON.stringify(data.furniture)) : []
            };

            this.planName = this.scene.meta.name;
            if (this.planNameInput) this.planNameInput.value = this.planName;

            this.selectedObjects = [];
            this.updatePropertiesPanel();
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
                    levelCount: Number(this.scene.meta?.levelCount) || 1,
                    levels: Array.isArray(this.scene.meta?.levels) ? this.scene.meta.levels : [{ level: 0, floorIndex: 0, name: 'Ground Floor', elevation: 0 }]
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
            const v = window.floorPlanViewer || window.viewer;
            if (v && typeof v.loadScene === 'function') {
                v.loadScene(sceneData);
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
