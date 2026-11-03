/**
 * FloorPlan3D - Frontend Application Controller
 * Manages user interactions, image uploads, AI progress animations,
 * 2D segmentation canvas overlays, and communicates with FloorPlanViewer.
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Initialize Three.js 3D Viewer
    const viewer = new FloorPlanViewer("threejs-canvas-container");
    window.floorPlanViewer = viewer;

    // DOM Element References
    const fileInput = document.getElementById("file-input");
    const dropZone = document.getElementById("drop-zone");
    const dropZonePrompt = document.getElementById("drop-zone-prompt");
    const imagePreviewContainer = document.getElementById("image-preview-container");
    const imagePreview = document.getElementById("image-preview");
    const btnRemoveImage = document.getElementById("btn-remove-image");
    const uploadReviewControls = document.getElementById("upload-review-controls");
    const uploadScaleCanvas = document.getElementById("upload-scale-canvas");
    const uploadScaleCtx = uploadScaleCanvas?.getContext("2d");
    const btnStartUploadCalibration = document.getElementById("btn-start-upload-calibration");
    const uploadKnownLength = document.getElementById("upload-known-length");
    const uploadScaleStatus = document.getElementById("upload-scale-status");
    const inputFloorCount = document.getElementById("input-floor-count");
    const inputSplitOrientation = document.getElementById("input-split-orientation");
    const inputSplitSliders = document.getElementById("input-split-sliders");
    const inputSplitPosition1 = document.getElementById("input-split-position-1");
    const inputSplitPosition2 = document.getElementById("input-split-position-2");
    const splitPosition2Wrap = document.getElementById("split-position-2-wrap");

    const btnGenerate = document.getElementById("btn-generate");
    const btnLoadDemo = document.getElementById("btn-load-demo");
    const btnLoadTwoStoryDemo = document.getElementById("btn-load-two-story-demo");
    const btnProcessBuilding = document.getElementById("btn-process-building");
    const buildingUploadStatus = document.getElementById("building-upload-status");
    const levelFilter = document.getElementById("level-filter");
    const appMessage = document.getElementById("app-message");
    const processingReady = document.body.dataset.processingReady === "true";
    const initialProcessingMode = document.body.dataset.processingMode || "OFFLINE";
    const processingModeBadge = document.getElementById("processing-mode-badge");

    // Sidebar Elements & Tab Controller (Declared early to avoid TDZ issues)
    const sidebarEl = document.getElementById("sidebar");
    const sidebarTabBtns = document.querySelectorAll(".sidebar-tab-btn");
    const sidebarPanels = document.querySelectorAll(".sidebar-panel");
    const sidebarContent = document.getElementById("sidebar-content");
    const sidebarSamplesSelect = document.getElementById("sidebar-samples-select");
    const btnJudgeHelp = document.getElementById("btn-judge-help");
    const popoverJudgeWalkthrough = document.getElementById("popover-judge-walkthrough");
    const btnCloseWalkthroughPopover = document.getElementById("btn-close-walkthrough-popover");
    const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
    const sidebarSheetHandle = document.getElementById("sidebar-sheet-handle");
    const btnCloseInspector = document.getElementById("btn-close-inspector");
    let activeSidebarTab = "input";

    function switchSidebarTab(tabName) {
        if (!tabName) return;
        activeSidebarTab = tabName;
        sidebarTabBtns.forEach(btn => {
            const isActive = btn.dataset.tab === tabName;
            btn.classList.toggle("active", isActive);
            btn.setAttribute("aria-selected", isActive ? "true" : "false");
            btn.setAttribute("tabindex", isActive ? "0" : "-1");
        });
        sidebarPanels.forEach(panel => {
            if (panel.id === `sidebar-panel-${tabName}`) {
                panel.classList.remove("hidden");
            } else {
                panel.classList.add("hidden");
            }
        });
        if (sidebarContent) {
            sidebarContent.scrollTop = 0;
        }
    }
    const progressContainer = document.getElementById("progress-container");
    const progressBar = document.getElementById("progress-bar");
    const progressStatus = document.getElementById("progress-status");

    // Sliders
    const inputMpp = document.getElementById("input-mpp");
    const labelMpp = document.getElementById("label-mpp");
    const chkAutoScale = document.getElementById("chk-auto-scale");
    const inputWallHeight = document.getElementById("input-wall-height");
    const labelWallHeight = document.getElementById("label-wall-height");
    const inputWallThickness = document.getElementById("input-wall-thickness");
    const labelWallThickness = document.getElementById("label-wall-thickness");

    // Camera preset buttons
    const btnViewIso = document.getElementById("btn-view-iso");
    const btnIsoRotateCcw = document.getElementById("btn-iso-rotate-ccw");
    const btnIsoRotateCw = document.getElementById("btn-iso-rotate-cw");
    const btnToggleOrbitFreely = document.getElementById("btn-toggle-orbit-freely");
    const btnViewTop = document.getElementById("btn-view-top");
    const btnViewEye = document.getElementById("btn-view-eye");
    const btnViewReset = document.getElementById("btn-view-reset");
    const btnCutaway = document.getElementById("btn-cutaway");

    // Layer checkboxes
    const chkWalls = document.getElementById("chk-walls");
    const chkFloors = document.getElementById("chk-floors");
    const chkRoof = document.getElementById("chk-roof");
    const chkLabels = document.getElementById("chk-labels");
    const chkOpenings = document.getElementById("chk-openings");
    const chkGrid = document.getElementById("chk-grid");
    const chkFurniture = document.getElementById("chk-furniture");
    const btnWalkthrough = document.getElementById("btn-walkthrough");
    const btnMeasure = document.getElementById("btn-measure");
    const measurementPanel = document.getElementById("measurement-panel");
    const measurementStatus = document.getElementById("measurement-status");
    const btnClearMeasurement = document.getElementById("btn-clear-measurement");

    // Tabs
    const tabBtns = document.querySelectorAll(".nav-tab-btn");
    const tabPanels = document.querySelectorAll(".tab-panel");

    // 2D Overlay canvas
    const segmentationCanvas = document.getElementById("segmentation-canvas");
    const segCtx = segmentationCanvas ? segmentationCanvas.getContext("2d") : null;
    const overlayScale = document.getElementById("overlay-scale");

    // JSON Viewer & Actions
    const jsonOutput = document.getElementById("json-output");
    const btnCopyJson = document.getElementById("btn-copy-json");
    const btnDownloadJson = document.getElementById("btn-download-json");
    const btnExportGlb = document.getElementById("btn-export-glb");
    const btnDownloadGlbTab = document.getElementById("btn-download-glb-tab");
    const roomSearch = document.getElementById("room-search");
    const btnFocusRoom = document.getElementById("btn-focus-room");
    const routeFrom = document.getElementById("route-from");
    const routeTo = document.getElementById("route-to");
    const btnShowRoute = document.getElementById("btn-show-route");
    const routeStatus = document.getElementById("route-status");
    const mapAssistantForm = document.getElementById("map-assistant-form");
    const mapAssistantQuestion = document.getElementById("map-assistant-question");
    const mapAssistantSubmit = document.getElementById("map-assistant-submit");
    const mapAssistantProvider = document.getElementById("map-assistant-provider");
    const mapAssistantAnswer = document.getElementById("map-assistant-answer");
    const btnAiPlanReview = document.getElementById("btn-ai-plan-review");
    const btnBuildingSummary = document.getElementById("btn-building-summary");
    const sceneInsightResult = document.getElementById("scene-insight-result");
    const museImagePrompt = document.getElementById("muse-image-prompt");
    const btnMuseImage = document.getElementById("btn-muse-image");
    const museImageStatus = document.getElementById("muse-image-status");
    const mapAudioInput = document.getElementById("map-audio-input");
    const btnTranscribeMap = document.getElementById("btn-transcribe-map");
    const mapTranscriptionStatus = document.getElementById("map-transcription-status");

    // Room Inspector Drawer
    const inspectorCard = document.getElementById("room-inspector-card");
    const inspectorEmpty = document.getElementById("room-inspector-empty");
    const inspectorTitle = document.getElementById("inspector-title");
    const inspectorType = document.getElementById("inspector-type");
    const inspectorConf = document.getElementById("inspector-conf");
    const inspectorArea = document.getElementById("inspector-area");
    const inspectorPoints = document.getElementById("inspector-points");
    const inspectorDoors = document.getElementById("inspector-doors");
    const areaSummaryTotal = document.getElementById("area-summary-total");
    const areaSummaryRooms = document.getElementById("area-summary-rooms");
    const mapQualityReport = document.getElementById("map-quality-report");
    const mapQualityChecks = document.getElementById("map-quality-checks");
    const mapQualityWarnings = document.getElementById("map-quality-warnings");
    const btnReview2D = document.getElementById("btn-review-2d");
    const btnReviewRoom = document.getElementById("btn-review-room");
    const editRoomName = document.getElementById("edit-room-name");
    const editRoomType = document.getElementById("edit-room-type");
    const btnSaveRoomEdit = document.getElementById("btn-save-room-edit");
    const btnDeleteRoom = document.getElementById("btn-delete-room");
    const btnEditBoundary = document.getElementById("btn-edit-boundary");
    const boundaryEditControls = document.getElementById("boundary-edit-controls");
    const boundaryEditStatus = document.getElementById("boundary-edit-status");
    const btnBoundaryUndo = document.getElementById("btn-boundary-undo");
    const btnBoundaryDone = document.getElementById("btn-boundary-done");
    const btnCalibrateScale = document.getElementById("btn-calibrate-scale");
    const btnApplyScale = document.getElementById("btn-apply-scale");
    const btnCancelScale = document.getElementById("btn-cancel-scale");
    const knownLength = document.getElementById("known-length");
    const scaleCalibrationStatus = document.getElementById("scale-calibration-status");
    const btnAddDoor2D = document.getElementById("btn-add-door-2d");
    const btnAddWindow2D = document.getElementById("btn-add-window-2d");
    const btnDeleteOpening2D = document.getElementById("btn-delete-opening-2d");
    const openingEditStatus = document.getElementById("opening-edit-status");

    // Application State
    let selectedFile = null;
    let selectedFiles = [];
    let currentSceneData = null;
    let currentOverlays = null;
    let loadedImageElement = null;
    let floorPlanImages = [];
    let isCutawayActive = false;
    let selectedRoomId = null;
    let polygonEditActive = false;
    let polygonEditDragIndex = null;
    let polygonEditUndoStack = [];
    let scaleCalibrationActive = false;
    let scaleCalibrationPoints = [];
    let uploadCalibrationActive = false;
    let uploadCalibrationPoints = [];
    let uploadScaleSource = "auto";
    let uploadPreviewImage = null;
    let activeUploadDivider = null;
    let openingEditMode = null;
    let selectedOpening = null;

    function uploadDividerFractions() {
        const count = Number(inputFloorCount?.value) || 1;
        if (count < 2) return [];
        const first = (Number(inputSplitPosition1?.value) || 50) / 100;
        return count === 3
            ? [first, (Number(inputSplitPosition2?.value) || 67) / 100]
            : [first];
    }

    function redrawUploadScaleCanvas() {
        if (!uploadScaleCanvas || !uploadScaleCtx || !uploadPreviewImage) return;
        const width = uploadPreviewImage.naturalWidth || uploadPreviewImage.width;
        const height = uploadPreviewImage.naturalHeight || uploadPreviewImage.height;
        if (!width || !height) return;
        uploadScaleCanvas.width = width;
        uploadScaleCanvas.height = height;
        uploadScaleCanvas.classList.remove("hidden");
        uploadScaleCtx.clearRect(0, 0, width, height);
        uploadScaleCtx.drawImage(uploadPreviewImage, 0, 0, width, height);

        const fractions = uploadDividerFractions();
        if (fractions.length) {
            uploadScaleCtx.save();
            uploadScaleCtx.strokeStyle = "#e23b2e";
            uploadScaleCtx.fillStyle = "#e23b2e";
            uploadScaleCtx.lineWidth = Math.max(3, Math.min(width, height) / 250);
            uploadScaleCtx.setLineDash([uploadScaleCtx.lineWidth * 3, uploadScaleCtx.lineWidth * 2]);
            fractions.forEach((fraction, index) => {
                const vertical = inputSplitOrientation?.value !== "horizontal";
                const position = fraction * (vertical ? width : height);
                uploadScaleCtx.beginPath();
                if (vertical) {
                    uploadScaleCtx.moveTo(position, 0);
                    uploadScaleCtx.lineTo(position, height);
                } else {
                    uploadScaleCtx.moveTo(0, position);
                    uploadScaleCtx.lineTo(width, position);
                }
                uploadScaleCtx.stroke();
                uploadScaleCtx.setLineDash([]);
                uploadScaleCtx.beginPath();
                uploadScaleCtx.arc(vertical ? position : width / 2, vertical ? height / 2 : position, Math.max(7, Math.min(width, height) / 55), 0, Math.PI * 2);
                uploadScaleCtx.fill();
                uploadScaleCtx.fillStyle = "#fff";
                uploadScaleCtx.font = `bold ${Math.max(12, Math.min(width, height) / 30)}px sans-serif`;
                uploadScaleCtx.textAlign = "center";
                uploadScaleCtx.textBaseline = "middle";
                uploadScaleCtx.fillText(String(index + 1), vertical ? position : width / 2, vertical ? height / 2 : position);
                uploadScaleCtx.fillStyle = "#e23b2e";
                uploadScaleCtx.setLineDash([uploadScaleCtx.lineWidth * 3, uploadScaleCtx.lineWidth * 2]);
            });
            uploadScaleCtx.restore();
        }

        if (uploadCalibrationPoints.length) {
            uploadScaleCtx.save();
            uploadScaleCtx.strokeStyle = "#00a6bd";
            uploadScaleCtx.fillStyle = "#00f3ff";
            uploadScaleCtx.lineWidth = Math.max(3, Math.min(width, height) / 250);
            uploadCalibrationPoints.forEach(([x, y], index) => {
                uploadScaleCtx.beginPath();
                uploadScaleCtx.arc(x, y, Math.max(8, Math.min(width, height) / 45), 0, Math.PI * 2);
                uploadScaleCtx.fill();
                uploadScaleCtx.stroke();
                uploadScaleCtx.fillStyle = "#08131b";
                uploadScaleCtx.font = `bold ${Math.max(12, Math.min(width, height) / 28)}px sans-serif`;
                uploadScaleCtx.textAlign = "center";
                uploadScaleCtx.textBaseline = "middle";
                uploadScaleCtx.fillText(String(index + 1), x, y);
                uploadScaleCtx.fillStyle = "#00f3ff";
            });
            if (uploadCalibrationPoints.length === 2) {
                uploadScaleCtx.beginPath();
                uploadScaleCtx.moveTo(...uploadCalibrationPoints[0]);
                uploadScaleCtx.lineTo(...uploadCalibrationPoints[1]);
                uploadScaleCtx.stroke();
            }
            uploadScaleCtx.restore();
        }
    }

    function updateUploadSplitControls() {
        const count = Number(inputFloorCount?.value) || 1;
        inputSplitSliders?.classList.toggle("hidden", count < 2);
        splitPosition2Wrap?.classList.toggle("hidden", count < 3);
        if (count === 3) {
            const first = Number(inputSplitPosition1?.value) || 33;
            let second = Number(inputSplitPosition2?.value) || 67;
            if (second < first + 8) {
                second = Math.min(92, first + 8);
                inputSplitPosition2.value = String(second);
            }
            inputSplitPosition2.min = String(Math.min(84, first + 8));
        }
        redrawUploadScaleCanvas();
    }

    function applyUploadCalibration() {
        const [first, second] = uploadCalibrationPoints;
        if (!first || !second) return;
        const known = Number(uploadKnownLength?.value);
        const pixels = Math.hypot(second[0] - first[0], second[1] - first[1]);
        const scale = known / pixels;
        if (!Number.isFinite(scale) || scale < 0.001 || scale > 0.1) {
            if (uploadScaleStatus) uploadScaleStatus.textContent = "That measurement is outside the supported scale range. Check the points and real length.";
            uploadCalibrationPoints = [];
            redrawUploadScaleCanvas();
            return;
        }
        uploadScaleSource = "user";
        if (inputMpp) inputMpp.value = String(scale);
        if (labelMpp) labelMpp.textContent = `${scale.toFixed(4)} m/px`;
        if (chkAutoScale) {
            chkAutoScale.checked = false;
            chkAutoScale.dispatchEvent(new Event("change"));
        }
        if (uploadScaleStatus) uploadScaleStatus.textContent = `User scale set to ${scale.toFixed(4)} m/px. The processor will validate it before creating 3D.`;
        uploadCalibrationActive = false;
        btnStartUploadCalibration?.classList.remove("calibration-active");
        btnStartUploadCalibration?.setAttribute("aria-pressed", "false");
        redrawUploadScaleCanvas();
    }

    function setProcessingBadge(mode, meta = null) {
        if (!processingModeBadge) return;
        const messages = {
            MOCK: "MOCK — PREPARED DATA",
            DEMO: "SAVED DEMO SCENE",
            READY: "SAM READY — NOT YET USED",
            LOCAL: "OPENCV ONLY",
        };
        let label = messages[mode] || messages.LOCAL;
        if (mode === "DEMO" && meta?.preparedSample) {
            label = String(meta?.labeling || "").toLowerCase() === "muse"
                ? "MUSE-LABELED · SAVED SCENE"
                : "SAVED SCENE · LOCAL GEOMETRY";
        } else if (meta && mode !== "MOCK" && mode !== "DEMO") {
            const segmentation = String(meta.segmentation || "").toLowerCase();
            if (segmentation.includes("sam-3.1")) {
                label = String(meta.labeling || "").toLowerCase() === "muse"
                    ? "SAM + MUSE"
                    : "SAM 3.1 — GENERIC LABELS";
            } else {
                label = String(meta.labeling || "").toLowerCase() === "muse" ? "OPENCV + MUSE" : "OPENCV ONLY";
            }
        } else if (mode === "READY") {
            label = messages.READY;
        }
        processingModeBadge.textContent = label;
        processingModeBadge.title = mode === "MOCK"
            ? "Prepared mock data. The uploaded floor plan was not analyzed."
            : mode === "DEMO" && meta?.preparedSample
                ? String(meta?.labeling || "").toLowerCase() === "muse"
                    ? "This saved scene contains room labels generated earlier by Meta Muse Spark. Its geometry is stored with the sample; loading it makes no new model call. Check Review for remaining items."
                    : "This saved scene uses stored geometry and local labels. Loading it makes no model call. Check Review for remaining items."
            : mode === "DEMO"
                ? "Curated sample scene with stored geometry and labels; loading it does not run a model."
                : meta?.segmentation?.toLowerCase?.().includes("sam-3.1")
                    ? "SAM masks contributed to the scene. Per-concept results and local fallbacks are listed in Review."
                    : String(meta?.labeling || "").toLowerCase() === "muse"
                        ? "Geometry was segmented locally and room names were generated by Muse."
                    : mode === "READY"
                        ? "SAM credentials are present; no SAM result has been used in a scene yet."
                        : "This scene was segmented with local OpenCV; no SAM masks were used.";
        processingModeBadge.classList.remove("hidden");
    }

    if (initialProcessingMode === "MOCK") setProcessingBadge(initialProcessingMode);
    async function initConfigStatusChip() {
        try {
            const res = await fetch("/api/config/status");
            if (!res.ok) return;
            const data = await res.json();
            if (!data) return;
            if (data.live_ready) {
                setProcessingBadge("READY");
            } else if (data.key_configured && data.mock_mode) {
                if (processingModeBadge) {
                    processingModeBadge.textContent = "MOCK MODE (KEY SET)";
                    processingModeBadge.title = "MODEL_API_KEY is configured, but MOCK_AI=1 is active.";
                    processingModeBadge.classList.remove("hidden");
                }
            }
        } catch (_) {
            // graceful ignore
        }
    }
    initConfigStatusChip();

    let appMessageTimer = null;
    function showMessage(message, kind = "info") {
        if (!appMessage) return;
        appMessage.textContent = message;
        appMessage.classList.remove("hidden", "border-rose-500/40", "text-rose-200", "border-amber-500/40", "text-amber-100", "border-blue-500/40", "text-blue-100");
        if (kind === "error") appMessage.classList.add("border-rose-500/40", "text-rose-200");
        else if (kind === "warning") appMessage.classList.add("border-amber-500/40", "text-amber-100");
        else appMessage.classList.add("border-blue-500/40", "text-blue-100");

        if (appMessageTimer) clearTimeout(appMessageTimer);
        appMessageTimer = setTimeout(() => {
            clearMessage();
        }, 4000);
    }

    function clearMessage() {
        if (appMessage) appMessage.classList.add("hidden");
    }

    function populateRoomControls(scene) {
        const rooms = scene.rooms || [];
        const levelNames = new Map((scene.meta.levels || []).map(level => [Number(level.level), level.name]));
        const fill = (select, placeholder) => {
            select.replaceChildren(new Option(placeholder, ""));
            rooms.forEach(room => {
                const levelName = levelNames.get(Number(room.level));
                const suffix = levelName ? ` · ${levelName}` : "";
                select.add(new Option(`${room.label || room.id} (${room.type || "room"})${suffix}`, room.id));
            });
        };
        fill(roomSearch, "Choose a room to focus");
        fill(routeFrom, "From room");
        fill(routeTo, "To room");
        if (rooms.length > 1) {
            routeFrom.value = rooms[0].id;
            routeTo.value = rooms[1].id;
            routeStatus.textContent = "Routes use detected doors and matching stairs or elevator rooms between floors.";
        } else {
            routeStatus.textContent = "At least two rooms are needed for a route.";
        }
        viewer.clearRoute();
        btnShowRoute.classList.remove("is-active");
    }

    function roomCentroid(room) {
        const polygon = room.polygon || [];
        if (polygon.length < 3) {
            if (!polygon.length) return [0, 0];
            return polygon.reduce((sum, point) => [sum[0] + point[0] / polygon.length, sum[1] + point[1] / polygon.length], [0, 0]);
        }
        let twiceArea = 0;
        let xSum = 0;
        let ySum = 0;
        polygon.forEach((point, index) => {
            const next = polygon[(index + 1) % polygon.length];
            const cross = point[0] * next[1] - next[0] * point[1];
            twiceArea += cross;
            xSum += (point[0] + next[0]) * cross;
            ySum += (point[1] + next[1]) * cross;
        });
        if (Math.abs(twiceArea) < 1e-8) {
            return polygon.reduce((sum, point) => [sum[0] + point[0] / polygon.length, sum[1] + point[1] / polygon.length], [0, 0]);
        }
        return [xSum / (3 * twiceArea), ySum / (3 * twiceArea)];
    }

    function polygonArea(polygon) {
        if (!polygon || polygon.length < 3) return 0;
        let twiceArea = 0;
        polygon.forEach((point, index) => {
            const next = polygon[(index + 1) % polygon.length];
            twiceArea += point[0] * next[1] - next[0] * point[1];
        });
        return Math.abs(twiceArea) / 2;
    }

    function roomArea(room) {
        const exterior = polygonArea(room?.polygon || []);
        const holes = (Array.isArray(room?.holes) ? room.holes : [])
            .reduce((sum, ring) => sum + polygonArea(ring), 0);
        return Math.max(0, exterior - holes);
    }

    function polygonHasSelfIntersection(polygon) {
        const orient = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
        const crosses = (a, b, c, d) => {
            const abC = orient(a, b, c), abD = orient(a, b, d);
            const cdA = orient(c, d, a), cdB = orient(c, d, b);
            return abC * abD < -1e-10 && cdA * cdB < -1e-10;
        };
        for (let i = 0; i < polygon.length; i++) {
            const iNext = (i + 1) % polygon.length;
            for (let j = i + 1; j < polygon.length; j++) {
                const jNext = (j + 1) % polygon.length;
                if (i === j || iNext === j || jNext === i) continue;
                if (crosses(polygon[i], polygon[iNext], polygon[j], polygon[jNext])) return true;
            }
        }
        return false;
    }

    function updateAreaSummary() {
        if (!currentSceneData) {
            if (areaSummaryTotal) areaSummaryTotal.textContent = "Load a plan to calculate areas.";
            if (areaSummaryRooms) areaSummaryRooms.replaceChildren();
            if (mapQualityReport) mapQualityReport.textContent = "Readiness checks appear after loading a scene.";
            if (mapQualityChecks) mapQualityChecks.replaceChildren();
            if (mapQualityWarnings) mapQualityWarnings.replaceChildren();
            return;
        }
        const rooms = currentSceneData.rooms || [];
        const meta = currentSceneData.meta || {};
        const totalArea = rooms.reduce((sum, room) => sum + roomArea(room), 0);
        const roomLevels = rooms.map(room => Number(room.floorIndex ?? room.level) || 0);
        const floorCount = Math.max(1, (meta.levels || []).length, Number(meta.levelCount) || 0, ...roomLevels.map(level => level + 1));
        if (areaSummaryTotal) {
            areaSummaryTotal.textContent = `${rooms.length} rooms, ${floorCount} ${floorCount === 1 ? "floor" : "floors"}, ${totalArea.toFixed(1)} m²`;
        }
        if (areaSummaryRooms) {
            areaSummaryRooms.replaceChildren();
            rooms.forEach(room => {
                const row = document.createElement("li");
                row.className = "flex justify-between gap-2 border-b border-hairline py-1 text-xs";
                const name = document.createElement("span");
                name.textContent = room.label || room.id;
                const area = document.createElement("span");
                area.className = "font-mono";
                area.textContent = `${roomArea(room).toFixed(1)} m²`;
                row.append(name, area);
                areaSummaryRooms.appendChild(row);
            });
        }
        const validRoomCount = rooms.filter(room => (room.polygon || []).length >= 3 && roomArea(room) > 0).length;
        const connectors = rooms.filter(room => ["stairs", "stair", "elevator"].includes(String(room.type || "").toLowerCase()));
        const connectorFloors = new Set(connectors.map(room => Number(room.floorIndex ?? room.level) || 0));
        const hasVerticalConnectorPair = floorCount < 2 || (
            connectorFloors.has(0)
            && Array.from({ length: floorCount - 1 }, (_, index) => index + 1).some(floor => connectorFloors.has(floor))
            && connectors.some(room => room.connectsTo && connectors.some(other =>
                other.id === room.connectsTo
                && (Number(other.floorIndex ?? other.level) || 0) !== (Number(room.floorIndex ?? room.level) || 0)
            ))
        );
        const walls = currentSceneData.walls || [];
        const doors = currentSceneData.doors || [];
        const windows = currentSceneData.windows || [];
        const warnings = Array.isArray(meta.warnings) ? meta.warnings : [];
        const genericLabel = label => /^room\s+\w+$/i.test(String(label || "").trim());
        const namedRoomCount = rooms.filter(room => room.confidence > 0 && !genericLabel(room.label)).length;
        const scaleMethod = String(meta.scaleMethod || "");
        const scaleSource = String(meta.scaleSource || "unverified");
        const scaleConfidence = Math.max(0, Math.min(1, Number(meta.scaleConfidence) || 0));
        const levelScaleNeedsReview = (meta.levels || []).some(level =>
            String(level.scaleSource || "").toLowerCase() === "needs-review"
        );
        const scaleNeedsReview = scaleSource.toLowerCase() === "needs-review" || levelScaleNeedsReview;
        const rows = [
            { state: validRoomCount === rooms.length && rooms.length > 0 ? "ok" : "review", label: "Room outlines", detail: `${validRoomCount} of ${rooms.length} have a usable polygon.` },
            { state: walls.length ? "ok" : "review", label: "Walls", detail: `${walls.length} wall region(s) in the scene.` },
            { state: doors.length ? "ok" : "review", label: "Doors", detail: `${doors.length} detected opening(s); check the 2D overlay for alignment.` },
            { state: windows.length ? "ok" : "review", label: "Windows", detail: `${windows.length} detected opening(s); check the 2D overlay for alignment.` },
            { state: scaleNeedsReview ? "review" : "ok", label: "Scale", detail: `${scaleSource} (${Math.round(scaleConfidence * 100)}% confidence): ${scaleMethod}.` },
            { state: hasVerticalConnectorPair ? "ok" : "review", label: "Floor connection", detail: floorCount < 2 ? "Single-story scene." : hasVerticalConnectorPair ? "A matching stair/elevator pair links the stories." : `${connectors.length} connector room(s) found; verify that a stair/elevator links both stories.` },
            { state: namedRoomCount === rooms.length && rooms.length > 0 ? "ok" : "review", label: "Room labels", detail: `${namedRoomCount} of ${rooms.length} have non-generic labels.` },
        ];
        const openingCounts = meta.openingCounts || {};
        if (Number(openingCounts.doorsDetected) || Number(openingCounts.windowsDetected)) {
            rows.push({
                state: Number(openingCounts.dropped) ? "review" : "ok",
                label: "Opening checks",
                detail: `Doors ${openingCounts.doorsKept ?? doors.length}/${openingCounts.doorsDetected ?? doors.length}; windows ${openingCounts.windowsKept ?? windows.length}/${openingCounts.windowsDetected ?? windows.length}; ${openingCounts.dropped || 0} dropped.`,
            });
        }
        const rejectedOpenings = (meta.openingDiagnostics || []).filter(item => item && item.accepted === false);
        if (rejectedOpenings.length) {
            const byReason = new Map();
            rejectedOpenings.forEach(item => {
                const rawReason = String(item.reason || "Rejected by geometry checks.");
                const reason = /^estimated .* width .* is outside /i.test(rawReason)
                    ? "Opening width outside the allowed range"
                    : /^nearest wall /i.test(rawReason) || /no wall within/i.test(rawReason)
                        ? "Candidate too far from a wall"
                        : rawReason;
                if (!byReason.has(reason)) byReason.set(reason, []);
                byReason.get(reason).push(item);
            });
            rows.push({ state: "review", kind: "opening-rejections", label: "Opening candidates rejected", detail: `${rejectedOpenings.length} total; grouped by reason.`, byReason });
        }
        if (meta.needsReview) {
            rows.unshift({ state: "review", label: "Needs review", detail: (meta.reviewIssues || []).join(" ") || "Quality checks failed; inspect the 2D overlay before viewing 3D." });
        }
        (meta.samConcepts || []).forEach(item => {
            const status = String(item.status || "UNKNOWN").toUpperCase();
            rows.push({
                state: status === "OK" ? "ok" : status === "NOT RUN" ? "info" : "review",
                label: `SAM ${item.concept || "concept"}`,
                detail: status === "OK"
                    ? `${item.used ? "Masks were used" : "Masks returned but local geometry was used"}${item.prompt && item.prompt !== item.concept ? ` with prompt “${item.prompt}”` : ""}${item.floorIndex !== undefined ? ` on floor ${Number(item.floorIndex) + 1}` : ""}.`
                    : status === "EMPTY"
                        ? `SAM completed but found no matching ${item.concept} regions; local fallback was used.`
                        : status === "NOT RUN"
                            ? "SAM was not run; local OpenCV handled this concept."
                            : `SAM failed safely (${item.category || "provider unavailable"}); local fallback was used.`,
            });
        });
        if (mapQualityChecks) {
            mapQualityChecks.replaceChildren();
            rows.forEach(item => {
                const row = document.createElement("li");
                row.className = "flex items-start gap-2 text-[12.5px] cursor-default";
                if (item.kind === "opening-rejections") {
                    const marker = document.createElement("span");
                    marker.className = "mono-check text-[var(--pigment)] shrink-0";
                    marker.textContent = "!";
                    marker.setAttribute("aria-label", "Review");
                    const details = document.createElement("details");
                    details.className = "min-w-0 text-[var(--secondary-ink)]";
                    const summary = document.createElement("summary");
                    summary.className = "cursor-pointer break-words";
                    summary.textContent = `${item.label}: ${item.detail}`;
                    details.appendChild(summary);
                    const reasonList = document.createElement("ul");
                    reasonList.className = "mt-1 ml-4 list-disc space-y-1";
                    item.byReason.forEach((candidates, reason) => {
                        const reasonRow = document.createElement("li");
                        reasonRow.textContent = `${reason} (${candidates.length})`;
                        const candidateDetails = document.createElement("details");
                        candidateDetails.className = "ml-2";
                        const candidateSummary = document.createElement("summary");
                        candidateSummary.className = "cursor-pointer";
                        candidateSummary.textContent = "Show candidates";
                        const candidateList = document.createElement("ul");
                        candidateList.className = "ml-4 list-disc";
                        candidates.forEach(candidate => {
                            const entry = document.createElement("li");
                            const point = Array.isArray(candidate.pixelCenter) ? ` at ${candidate.pixelCenter.map(value => Number(value).toFixed(0)).join(", ")} px` : "";
                            entry.textContent = `${String(candidate.kind || "opening").toUpperCase()} ${candidate.candidate || "candidate"}${point}`;
                            candidateList.appendChild(entry);
                        });
                        candidateDetails.append(candidateSummary, candidateList);
                        reasonRow.appendChild(candidateDetails);
                        reasonList.appendChild(reasonRow);
                    });
                    details.appendChild(reasonList);
                    row.append(marker, details);
                    mapQualityChecks.appendChild(row);
                    return;
                }
                row.title = `${item.label}: ${item.detail}`;
                const marker = document.createElement("span");
                marker.className = item.state === "ok" ? "mono-check text-[var(--ink)]" : "mono-check text-[var(--pigment)]";
                marker.textContent = item.state === "ok" ? "OK" : "!";
                marker.setAttribute("aria-label", item.state === "ok" ? "Checked" : "Review");
                const text = document.createElement("span");
                text.className = "min-w-0 whitespace-normal break-words text-[var(--secondary-ink)]";
                text.textContent = `${item.label}: ${item.detail}`;
                row.append(marker, text);
                mapQualityChecks.appendChild(row);
            });
        }
        if (mapQualityWarnings) {
            mapQualityWarnings.replaceChildren();
            const warningItems = warnings.length ? warnings : ["No pipeline warnings recorded."];
            warningItems.forEach(warning => {
                const row = document.createElement("li");
                row.className = "flex items-center gap-2 text-[12.5px] truncate cursor-default";
                row.title = String(warning);
                const marker = document.createElement("span");
                marker.className = warnings.length ? "mono-check text-[var(--pigment)]" : "mono-check text-[var(--ink)]";
                marker.textContent = warnings.length ? "!" : "OK";
                marker.setAttribute("aria-label", warnings.length ? "Warning" : "Checked");
                const text = document.createElement("span");
                text.className = "truncate text-[var(--secondary-ink)]";
                text.textContent = String(warning);
                row.append(marker, text);
                mapQualityWarnings.appendChild(row);
            });
        }
        if (mapQualityReport) {
            mapQualityReport.textContent = `${rooms.length} rooms, ${floorCount} ${floorCount === 1 ? "floor" : "floors"}, ${totalArea.toFixed(1)} m² estimated area.`;
        }
    }

    if (btnReview2D) {
        btnReview2D.addEventListener("click", () => {
            if (!currentSceneData) {
                showMessage("Load a demo or plan before reviewing 2D detections.", "info");
                return;
            }
            const tab2d = document.querySelector('[data-tab="2d"]');
            if (tab2d) tab2d.click();
        });
    }

    if (btnReviewRoom) {
        btnReviewRoom.addEventListener("click", () => {
            if (!currentSceneData || !loadedImageElement) {
                showMessage("Load a demo or upload a plan before editing a room outline.", "info");
                return;
            }
            const rooms = currentSceneData.rooms || [];
            const room = rooms.find(item => (item.polygon || []).length < 3 || polygonHasSelfIntersection(item.polygon)) || rooms[0];
            if (!room) {
                showMessage("There are no room outlines available to edit.", "warning");
                return;
            }
            if (typeof window.onFloorPlanRoomSelected === "function") {
                window.onFloorPlanRoomSelected(room);
            }
            if (btnEditBoundary) btnEditBoundary.click();
        });
    }

    function refreshEditedScene() {
        if (!currentSceneData) return;
        if (currentSceneData.meta?.needsReview) {
            viewer.clear();
            viewer.hideLoadingState();
        } else {
            viewer.loadScene(currentSceneData, { animateBuild: false, resetCamera: false });
        }
        jsonOutput.textContent = JSON.stringify(currentSceneData, null, 2);
        updateAreaSummary();
        populateRoomControls(currentSceneData);
        if (loadedImageElement) render2DSegmentationCanvas();
        if (inspectorCard) inspectorCard.classList.add("hidden");
        if (inspectorEmpty) inspectorEmpty.classList.remove("hidden");
        selectedRoomId = null;
        [editRoomName, editRoomType, btnSaveRoomEdit, btnDeleteRoom].forEach(control => { if (control) control.disabled = true; });
        if (btnEditBoundary) btnEditBoundary.disabled = true;
    }

    function levelInfoFor(levelIndex) {
        return (currentSceneData?.meta?.levels || []).find(level => Number(level.level ?? level.floorIndex) === Number(levelIndex));
    }

    function scaleForLevel(levelIndex) {
        return Number(levelInfoFor(levelIndex)?.metersPerPixel) || Number(currentSceneData?.meta?.metersPerPixel) || 0.02;
    }

    function offsetForLevel(levelIndex) {
        const offset = levelInfoFor(levelIndex)?.planOffset || [0, 0];
        return [Number(offset[0]) || 0, Number(offset[1]) || 0];
    }

    function entityFloorIndex(item) {
        return Number(item?.level ?? item?.floorIndex) || 0;
    }

    function scenePointToSourcePixels(item, point) {
        const floor = entityFloorIndex(item);
        const mpp = scaleForLevel(floor);
        const offset = offsetForLevel(floor);
        return [(Number(point[0]) - offset[0]) / mpp, (Number(point[1]) - offset[1]) / mpp];
    }

    function sourcePixelsToScenePoint(point, floorIndex) {
        const mpp = scaleForLevel(floorIndex);
        const offset = offsetForLevel(floorIndex);
        return [Number(point[0]) * mpp + offset[0], Number(point[1]) * mpp + offset[1]];
    }

    async function rebuildEditedGeometry(candidate, successText = "2D edits saved.") {
        try {
            if (openingEditStatus) openingEditStatus.textContent = "Rebuilding walls and openings locally…";
            const response = await fetch("/api/scene/rebuild-geometry", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ scene: candidate }),
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || "Geometry could not be rebuilt.");
            currentSceneData = result.scene;
            window.currentSceneData = currentSceneData;
            selectedOpening = null;
            if (btnDeleteOpening2D) btnDeleteOpening2D.disabled = true;
            refreshEditedScene();
            if (openingEditStatus) openingEditStatus.textContent = "Geometry updated locally. SAM was not called again.";
            showMessage(successText, "info");
            return true;
        } catch (error) {
            if (openingEditStatus) openingEditStatus.textContent = error.message || "Could not rebuild geometry.";
            showMessage(error.message || "Could not rebuild the edited geometry.", "error");
            return false;
        }
    }

    function refreshBoundaryScene() {
        if (!currentSceneData) return;
        currentSceneData.rooms.forEach(room => {
            room.area_m2 = roomArea(room);
            room.centroid = roomCentroid(room);
        });
        const roomId = selectedRoomId;
        rebuildEditedGeometry(JSON.parse(JSON.stringify(currentSceneData)), "Room outline saved; wall geometry was rebuilt locally.").then(success => {
            if (!success) return;
            const room = currentSceneData.rooms.find(item => item.id === roomId);
            if (room) {
                window.onFloorPlanRoomSelected(room);
                viewer.previewRoomBoundary(room);
            }
        });
    }

    function showRoomRoute(scene, startId, endId) {
        const rooms = new Map((scene.rooms || []).map(room => [room.id, room]));
        if (!rooms.has(startId) || !rooms.has(endId) || startId === endId) {
            routeStatus.textContent = "Choose two different rooms.";
            viewer.clearRoute();
        btnShowRoute.classList.remove("is-active");
            return;
        }

        const graph = new Map();
        const nodeCoordinates = new Map();
        const addNode = (id, coordinates) => {
            if (!graph.has(id)) graph.set(id, []);
            nodeCoordinates.set(id, coordinates);
        };
        const roomNode = id => `room:${id}`;
        const roomLevel = room => Number(room?.floorIndex ?? room?.level) || 0;
        const floorElevation = floorIndex => {
            const info = (scene.meta.levels || []).find(item => Number(item.floorIndex ?? item.level) === floorIndex);
            return Number.isFinite(Number(info?.elevation))
                ? Number(info.elevation)
                : floorIndex * (Number(scene.meta.floorHeight) || 3.2);
        };
        rooms.forEach(room => addNode(roomNode(room.id), {
            point: roomCentroid(room),
            floorIndex: roomLevel(room)
        }));

        (scene.doors || []).forEach((door, doorIndex) => {
            const center = door.center || [0, 0];
            const allConnected = (door.connects || []).filter(id => rooms.has(id));
            const explicitDoorFloor = door.floorIndex ?? door.level;
            const doorFloor = explicitDoorFloor === undefined || explicitDoorFloor === null
                ? (allConnected.length ? roomLevel(rooms.get(allConnected[0])) : roomLevel(door))
                : Number(explicitDoorFloor) || 0;
            const connected = allConnected.filter(id => roomLevel(rooms.get(id)) === doorFloor);
            if (connected.length < 2) return;

            const doorNode = `door:${door.id ?? doorIndex}`;
            addNode(doorNode, { point: center, floorIndex: doorFloor });
            connected.forEach(roomId => {
                const roomIdNode = roomNode(roomId);
                const roomCenter = roomCentroid(rooms.get(roomId));
                const distance = Math.hypot(roomCenter[0] - center[0], roomCenter[1] - center[1]);
                graph.get(roomIdNode).push({ to: doorNode, cost: distance });
                graph.get(doorNode).push({ to: roomIdNode, cost: distance });
            });
        });

        // Stair/elevator rooms are the only graph links allowed between floors.
        const verticalConnectors = new Map();
        rooms.forEach(room => {
            const type = String(room.type || "").toLowerCase();
            if (!(["stairs", "stair", "elevator"].includes(type))) return;
            const connectorKey = type === "stair" ? "stairs" : type;
            if (!verticalConnectors.has(connectorKey)) verticalConnectors.set(connectorKey, []);
            verticalConnectors.get(connectorKey).push(room);
        });
        verticalConnectors.forEach(connectors => {
            connectors.sort((a, b) => roomLevel(a) - roomLevel(b));
            for (let i = 0; i < connectors.length; i++) {
                for (let j = i + 1; j < connectors.length; j++) {
                    const lower = connectors[i], upper = connectors[j];
                    const lowerFloor = roomLevel(lower), upperFloor = roomLevel(upper);
                    if (lowerFloor === upperFloor) continue;
                    const lowerCenter = roomCentroid(lower), upperCenter = roomCentroid(upper);
                    const transition = [(lowerCenter[0] + upperCenter[0]) / 2, (lowerCenter[1] + upperCenter[1]) / 2];
                    const lowerNode = roomNode(lower.id), upperNode = roomNode(upper.id);
                    const verticalCost = Math.abs(floorElevation(upperFloor) - floorElevation(lowerFloor));
                    const horizontalOffset = Math.hypot(lowerCenter[0] - transition[0], lowerCenter[1] - transition[1])
                        + Math.hypot(upperCenter[0] - transition[0], upperCenter[1] - transition[1]);
                    const cost = verticalCost + horizontalOffset;
                    const lowerVia = [
                        { point: transition, floorIndex: lowerFloor },
                        { point: transition, floorIndex: upperFloor }
                    ];
                    const upperVia = [
                        { point: transition, floorIndex: upperFloor },
                        { point: transition, floorIndex: lowerFloor }
                    ];
                    graph.get(lowerNode).push({ to: upperNode, cost, via: lowerVia });
                    graph.get(upperNode).push({ to: lowerNode, cost, via: upperVia });
                }
            }
        });

        const startNode = roomNode(startId);
        const endNode = roomNode(endId);
        const distances = new Map([...graph.keys()].map(id => [id, Infinity]));
        const previous = new Map();
        const pending = new Set(graph.keys());
        distances.set(startNode, 0);
        while (pending.size) {
            let current = null;
            for (const id of pending) if (current === null || distances.get(id) < distances.get(current)) current = id;
            if (current === null || !Number.isFinite(distances.get(current))) break;
            pending.delete(current);
            if (current === endNode) break;
            for (const edge of graph.get(current)) {
                const candidate = distances.get(current) + edge.cost;
                if (candidate < distances.get(edge.to)) {
                    distances.set(edge.to, candidate);
                    previous.set(edge.to, { from: current, via: edge.via || [] });
                }
            }
        }

        if (!previous.has(endNode)) {
            routeStatus.textContent = "No route found: the detected doors do not connect these rooms.";
            viewer.clearRoute();
        btnShowRoute.classList.remove("is-active");
            return;
        }
        const path = [];
        const links = [];
        let cursor = endNode;
        while (cursor !== startNode) {
            path.unshift(cursor);
            const link = previous.get(cursor);
            if (!link) break;
            links.unshift(link);
            cursor = link.from;
            if (!cursor) break;
        }
        path.unshift(startNode);
        const coordinates = [];
        path.forEach((nodeId, index) => {
            coordinates.push(nodeCoordinates.get(nodeId));
            if (links[index]) coordinates.push(...links[index].via);
        });
        const doorCount = path.filter(nodeId => nodeId.startsWith("door:")).length;
        const floorChanges = coordinates.filter((point, index) => index > 0
            && point.floorIndex !== coordinates[index - 1].floorIndex).length;
        viewer.drawRoute(coordinates);
        btnShowRoute.classList.add("is-active");
        routeStatus.textContent = `Route shown through ${doorCount} door${doorCount === 1 ? "" : "s"} and ${floorChanges} floor change${floorChanges === 1 ? "" : "s"}.`;
    }

    if (btnFocusRoom) {
        btnFocusRoom.addEventListener("click", () => {
            const room = (currentSceneData?.rooms || []).find(item => item.id === (roomSearch ? roomSearch.value : ""));
            if (!room) {
                if (routeStatus) routeStatus.textContent = "Load a scene and choose a room first.";
                return;
            }
            if (viewer) viewer.focusRoom(room);
            if (typeof window.onFloorPlanRoomSelected === "function") {
                window.onFloorPlanRoomSelected(room);
            }
        });
    }

    if (btnShowRoute) {
        btnShowRoute.addEventListener("click", () => {
            if (!currentSceneData) {
                if (routeStatus) routeStatus.textContent = "Load a scene before creating a route.";
                return;
            }
            if (routeFrom && routeTo) {
                showRoomRoute(currentSceneData, routeFrom.value, routeTo.value);
            }
        });
    }

    async function requestSceneInsight(kind, button) {
        if (!currentSceneData) {
            sceneInsightResult.textContent = "Load a demo or process a plan first.";
            sceneInsightResult.classList.remove("hidden");
            return;
        }
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = kind === "review" ? "Reviewing…" : "Summarizing…";
        sceneInsightResult.textContent = "Checking the current scene…";
        sceneInsightResult.classList.remove("hidden");
        try {
            const response = await fetch("/api/scene/insight", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ kind, scene: currentSceneData }),
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || "Scene analysis failed.");
            sceneInsightResult.replaceChildren();
            const provider = document.createElement("p");
            provider.className = "mb-1 font-mono text-[10px]";
            provider.textContent = result.provider;
            const answer = document.createElement("p");
            answer.textContent = result.answer;
            sceneInsightResult.append(provider, answer);
            if (kind === "review" && Array.isArray(result.review?.findings)) {
                const checklist = document.createElement("ul");
                checklist.className = "mt-2 space-y-1 border-t border-bauhaus-ink pt-2";
                result.review.findings.forEach(item => {
                    const row = document.createElement("li");
                    row.textContent = `${item.status === "check" ? "! Review" : item.status === "ok" ? "Checked" : "Info"}: ${item.title} — ${item.detail}`;
                    checklist.appendChild(row);
                });
                sceneInsightResult.appendChild(checklist);
                (result.review.warnings || []).forEach(warning => {
                    const row = document.createElement("p");
                    row.className = "mt-1 text-bauhaus-red";
                    row.textContent = `Warning: ${warning}`;
                    sceneInsightResult.appendChild(row);
                });
            }
        } catch (error) {
            sceneInsightResult.textContent = error.message || "Scene analysis failed.";
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    btnAiPlanReview.addEventListener("click", () => requestSceneInsight("review", btnAiPlanReview));
    btnBuildingSummary.addEventListener("click", () => requestSceneInsight("summary", btnBuildingSummary));

    mapAssistantForm.addEventListener("submit", async event => {
        event.preventDefault();
        if (!currentSceneData) {
            mapAssistantAnswer.textContent = "Load or process a floor plan before asking about it.";
            mapAssistantAnswer.classList.remove("hidden");
            return;
        }
        mapAssistantSubmit.disabled = true;
        mapAssistantSubmit.textContent = "Checking the map…";
        mapAssistantProvider.textContent = "Checking…";
        try {
            const response = await fetch("/api/scene/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: mapAssistantQuestion.value.trim(), scene: currentSceneData }),
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || "Could not query this map.");
            if (result.route) {
                routeFrom.value = result.route.startId;
                routeTo.value = result.route.endId;
                showRoomRoute(currentSceneData, result.route.startId, result.route.endId);
            }
            mapAssistantAnswer.textContent = result.answer;
            mapAssistantProvider.textContent = result.provider;
        } catch (error) {
            mapAssistantAnswer.textContent = error.message || "Could not query this map.";
            mapAssistantProvider.textContent = "Question unavailable";
        } finally {
            mapAssistantAnswer.classList.remove("hidden");
            mapAssistantSubmit.disabled = false;
            mapAssistantSubmit.textContent = "Ask map assistant";
        }
    });

    btnMuseImage.addEventListener("click", async () => {
        btnMuseImage.disabled = true;
        museImageStatus.textContent = "Muse Image is creating a draft…";
        try {
            const response = await fetch("/api/generate-floorplan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: museImagePrompt.value.trim() }),
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || "Could not generate a plan.");
            const blob = await (await fetch(result.imageUrl)).blob();
            const generatedFile = new File([blob], "muse-image-draft.png", { type: "image/png" });
            handleFileSelection([generatedFile]);
            museImageStatus.textContent = "Draft generated and loaded for review. Select Process to build the 3D estimate.";
            showMessage("Muse Image created a visual draft. Check its walls and room boundaries before processing; dimensions are not guaranteed.", "warning");
        } catch (error) {
            museImageStatus.textContent = error.message || "Muse Image is unavailable.";
        } finally {
            btnMuseImage.disabled = false;
        }
    });

    if (btnTranscribeMap) {
        btnTranscribeMap.addEventListener("click", async () => {
            if (!mapAudioInput || !mapAudioInput.files || !mapAudioInput.files.length) {
                if (mapTranscriptionStatus) mapTranscriptionStatus.textContent = "Choose a supported mono PCM WAV recording first.";
                return;
            }
            btnTranscribeMap.disabled = true;
            if (mapTranscriptionStatus) mapTranscriptionStatus.textContent = "Transcribing…";
            try {
                const formData = new FormData();
                formData.append("audio", mapAudioInput.files[0]);
                const response = await fetch("/api/transcribe", { method: "POST", body: formData });
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.error || "Transcription failed.");
                if (mapAssistantQuestion) mapAssistantQuestion.value = result.transcript;
                if (mapTranscriptionStatus) mapTranscriptionStatus.textContent = "Transcript added to the question box. Review it, then select Ask map assistant.";
            } catch (error) {
                if (mapTranscriptionStatus) mapTranscriptionStatus.textContent = error.message || "Transcription is unavailable.";
            } finally {
                btnTranscribeMap.disabled = false;
            }
        });
    }

    // -------------------------------------------------------------
    // Slider Events
    // -------------------------------------------------------------
    if (inputMpp && labelMpp) {
        inputMpp.addEventListener("input", (e) => {
            labelMpp.textContent = `${parseFloat(e.target.value).toFixed(3)} m/px`;
            if (!chkAutoScale?.checked && uploadScaleSource !== "user") {
                uploadScaleSource = "manual";
                if (uploadScaleStatus) uploadScaleStatus.textContent = "Manual scale selected. The processor will check it against building and room size limits.";
            }
        });
    }

    if (chkAutoScale && inputMpp) {
        chkAutoScale.addEventListener("change", () => {
            inputMpp.disabled = chkAutoScale.checked;
            inputMpp.classList.toggle("opacity-40", chkAutoScale.checked);
            if (uploadScaleSource !== "user") uploadScaleSource = chkAutoScale.checked ? "auto" : "manual";
        });
        inputMpp.disabled = chkAutoScale.checked;
        inputMpp.classList.toggle("opacity-40", chkAutoScale.checked);
    }

    if (inputWallHeight && labelWallHeight) {
        inputWallHeight.addEventListener("input", (e) => {
            const val = parseFloat(e.target.value).toFixed(1);
            labelWallHeight.textContent = `${val} m`;
            if (viewer) viewer.setWallHeight(val);
        });
    }

    if (inputWallThickness && labelWallThickness) {
        inputWallThickness.addEventListener("input", (e) => {
            const value = parseFloat(e.target.value);
            labelWallThickness.textContent = `${value.toFixed(2)} m`;
        });
        inputWallThickness.addEventListener("change", e => {
            if (viewer) viewer.setWallThickness(parseFloat(e.target.value));
        });
    }

    // -------------------------------------------------------------
    // Drag & Drop / File Selection
    // -------------------------------------------------------------
    if (dropZone && fileInput) {
        dropZone.addEventListener("click", () => fileInput.click());
    }

    if (fileInput) {
        fileInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files.length) handleFileSelection(Array.from(e.target.files));
        });
    }

    btnStartUploadCalibration?.addEventListener("click", () => {
        if (!uploadPreviewImage) {
            if (uploadScaleStatus) uploadScaleStatus.textContent = "Choose a floor plan image before setting its scale.";
            return;
        }
        uploadCalibrationActive = true;
        uploadCalibrationPoints = [];
        uploadScaleSource = "auto";
        btnStartUploadCalibration.classList.add("calibration-active");
        btnStartUploadCalibration.setAttribute("aria-pressed", "true");
        if (uploadScaleStatus) uploadScaleStatus.textContent = "Click the first endpoint, then the second endpoint of a known length.";
        redrawUploadScaleCanvas();
    });

    uploadScaleCanvas?.addEventListener("click", event => {
        if (!uploadCalibrationActive || !uploadScaleCanvas) return;
        const rect = uploadScaleCanvas.getBoundingClientRect();
        const point = [
            Math.max(0, Math.min(uploadScaleCanvas.width, (event.clientX - rect.left) * uploadScaleCanvas.width / rect.width)),
            Math.max(0, Math.min(uploadScaleCanvas.height, (event.clientY - rect.top) * uploadScaleCanvas.height / rect.height)),
        ];
        uploadCalibrationPoints.push(point);
        if (uploadCalibrationPoints.length === 1 && uploadScaleStatus) uploadScaleStatus.textContent = "First point saved. Click the second endpoint.";
        if (uploadCalibrationPoints.length === 2) applyUploadCalibration();
        redrawUploadScaleCanvas();
    });

    uploadScaleCanvas?.addEventListener("pointerdown", event => {
        if (uploadCalibrationActive || Number(inputFloorCount?.value) < 2 || !uploadPreviewImage) return;
        const rect = uploadScaleCanvas.getBoundingClientRect();
        const vertical = inputSplitOrientation?.value !== "horizontal";
        const pointerPosition = vertical ? event.clientX - rect.left : event.clientY - rect.top;
        const displayLength = vertical ? rect.width : rect.height;
        const linePositions = uploadDividerFractions().map(fraction => fraction * displayLength);
        const nearest = linePositions.map((value, index) => ({ index, distance: Math.abs(value - pointerPosition) }))
            .sort((a, b) => a.distance - b.distance)[0];
        if (!nearest || nearest.distance > 18) return;
        activeUploadDivider = nearest.index;
        uploadScaleCanvas.setPointerCapture(event.pointerId);
        event.preventDefault();
    });

    uploadScaleCanvas?.addEventListener("pointermove", event => {
        if (activeUploadDivider === null) return;
        const rect = uploadScaleCanvas.getBoundingClientRect();
        const vertical = inputSplitOrientation?.value !== "horizontal";
        const coordinate = vertical ? event.clientX - rect.left : event.clientY - rect.top;
        const displayLength = vertical ? rect.width : rect.height;
        let percent = Math.max(8, Math.min(92, coordinate / displayLength * 100));
        if (Number(inputFloorCount?.value) === 3) {
            if (activeUploadDivider === 0) percent = Math.min(percent, Number(inputSplitPosition2.value) - 8);
            else percent = Math.max(percent, Number(inputSplitPosition1.value) + 8);
        }
        const slider = activeUploadDivider === 0 ? inputSplitPosition1 : inputSplitPosition2;
        if (slider) slider.value = String(Math.round(percent));
        updateUploadSplitControls();
        event.preventDefault();
    });

    const finishUploadDividerDrag = () => { activeUploadDivider = null; };
    uploadScaleCanvas?.addEventListener("pointerup", finishUploadDividerDrag);
    uploadScaleCanvas?.addEventListener("pointercancel", finishUploadDividerDrag);
    [inputFloorCount, inputSplitOrientation, inputSplitPosition1, inputSplitPosition2].forEach(control => {
        control?.addEventListener("input", updateUploadSplitControls);
        control?.addEventListener("change", updateUploadSplitControls);
    });

    if (dropZone) {
        dropZone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropZone.classList.add("drag-active");
        });

        dropZone.addEventListener("dragleave", () => {
            dropZone.classList.remove("drag-active");
        });

        dropZone.addEventListener("drop", (e) => {
            e.preventDefault();
            dropZone.classList.remove("drag-active");
            if (e.dataTransfer.files && e.dataTransfer.files.length) handleFileSelection(Array.from(e.dataTransfer.files));
        });
    }

    if (btnRemoveImage) {
        btnRemoveImage.addEventListener("click", (e) => {
            e.stopPropagation();
            selectedFile = null;
            selectedFiles = [];
            uploadCalibrationActive = false;
            uploadCalibrationPoints = [];
            uploadPreviewImage = null;
            uploadScaleSource = "auto";
            if (fileInput) fileInput.value = "";
            if (imagePreviewContainer) imagePreviewContainer.classList.add("hidden");
            if (uploadReviewControls) uploadReviewControls.classList.add("hidden");
            if (dropZonePrompt) dropZonePrompt.classList.remove("hidden");
            if (btnGenerate) btnGenerate.disabled = true;
            if (btnProcessBuilding) btnProcessBuilding.classList.add("hidden");
            if (buildingUploadStatus) buildingUploadStatus.classList.add("hidden");
            clearMessage();
        });
    }

    function handleFileSelection(files) {
        const valid = files.filter(file => ["image/png", "image/jpeg", "image/webp"].includes(file.type.toLowerCase()) && file.size <= 10 * 1024 * 1024);
        if (!valid.length) {
            showMessage("Choose PNG, JPG, or WebP floor plans, each 10 MB or smaller.", "error");
            return;
        }
        clearMessage();
        selectedFiles = valid.slice(0, 8);
        selectedFile = selectedFiles[0];
        uploadCalibrationActive = false;
        uploadCalibrationPoints = [];
        uploadScaleSource = "auto";
        const multiple = selectedFiles.length > 1;
        btnProcessBuilding.classList.toggle("hidden", !multiple);
        btnProcessBuilding.disabled = !processingReady || !multiple;
        buildingUploadStatus.classList.toggle("hidden", !multiple);
        buildingUploadStatus.textContent = multiple
            ? `${selectedFiles.length} plans selected. Order them ground-to-top; detected stair/elevator regions help align the stories.`
            : "";
        if (valid.length !== files.length || valid.length > 8) showMessage("Only the first eight valid PNG, JPG, or WebP plans (up to 10 MB each) are used.", "warning");
        const reader = new FileReader();
        reader.onload = (event) => {
            imagePreview.src = event.target.result;
            imagePreviewContainer.classList.remove("hidden");
            uploadReviewControls?.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");
            btnGenerate.disabled = !processingReady || !selectedFile;

            // Pre-load image for 2D canvas
            const img = new Image();
            img.onload = () => {
                loadedImageElement = img;
                uploadPreviewImage = img;
                redrawUploadScaleCanvas();
                updateUploadSplitControls();
                if (currentSceneData) render2DSegmentationCanvas();
            };
            img.src = event.target.result;
        };
        reader.readAsDataURL(selectedFile);
    }

    // -------------------------------------------------------------
    // Camera Presets & Layer Toggles
    // -------------------------------------------------------------
    function updateCameraPresetActiveUI(mode) {
        btnViewIso?.classList.remove("is-active");
        btnViewTop?.classList.remove("is-active");
        btnViewEye?.classList.remove("is-active");
        btnToggleOrbitFreely?.classList.remove("is-active");
        btnToggleOrbitFreely?.setAttribute("aria-pressed", "false");

        if (mode === "isometric") {
            btnViewIso?.classList.add("is-active");
        } else if (mode === "orbit-freely") {
            btnToggleOrbitFreely?.classList.add("is-active");
            btnToggleOrbitFreely?.setAttribute("aria-pressed", "true");
        } else if (mode === "top-down") {
            btnViewTop?.classList.add("is-active");
        } else if (mode === "eye-level") {
            btnViewEye?.classList.add("is-active");
        }
    }

    if (viewer) {
        viewer.onCameraModeChange = (mode) => updateCameraPresetActiveUI(mode);
        updateCameraPresetActiveUI("isometric");
    }

    btnViewIso?.addEventListener("click", () => {
        viewer.setIsometricView();
    });
    btnIsoRotateCcw?.addEventListener("click", () => {
        viewer.rotateIsometricView(-90);
    });
    btnIsoRotateCw?.addEventListener("click", () => {
        viewer.rotateIsometricView(90);
    });
    btnToggleOrbitFreely?.addEventListener("click", () => {
        viewer.toggleOrbitFreely();
    });
    btnViewTop?.addEventListener("click", () => {
        viewer.setTopDownView();
    });
    btnViewEye?.addEventListener("click", () => {
        if (isCutawayActive) {
            isCutawayActive = false;
            btnCutaway.classList.remove("bg-amber-600", "text-white");
            btnCutaway.classList.add("bg-slate-800", "text-slate-300");
            const originalHeight = parseFloat(inputWallHeight.value) || 3.0;
            viewer.setWallHeight(originalHeight, { syncFloors: false });
            labelWallHeight.textContent = `${originalHeight.toFixed(1)} m`;
        }
        viewer.setEyeLevelView();
    });
    btnViewReset?.addEventListener("click", () => {
        viewer.resetCameraView();
    });
    if (levelFilter) {
        levelFilter.addEventListener("change", () => {
            if (viewer) viewer.setVisibleLevel(levelFilter.value === "all" ? null : levelFilter.value);
            if (floorPlanImages.length > 1) {
                const imageIndex = levelFilter.value === "all" ? 0 : Number(levelFilter.value);
                loadedImageElement = floorPlanImages[imageIndex] || floorPlanImages[0];
            }
            if (loadedImageElement) render2DSegmentationCanvas();
        });
    }

    if (btnCutaway) {
        btnCutaway.addEventListener("click", () => {
            isCutawayActive = !isCutawayActive;
            if (isCutawayActive) {
                btnCutaway.classList.add("bg-amber-600", "text-white");
                btnCutaway.classList.remove("bg-slate-800", "text-slate-300");
                if (viewer) viewer.setWallHeight(1.1, { syncFloors: false }); // Cutaway height only; preserve story spacing.
                if (labelWallHeight) labelWallHeight.textContent = "1.1 m (Cutaway)";
            } else {
                btnCutaway.classList.remove("bg-amber-600", "text-white");
                btnCutaway.classList.add("bg-slate-800", "text-slate-300");
                const originalHeight = parseFloat(inputWallHeight?.value) || 3.0;
                if (viewer) viewer.setWallHeight(originalHeight, { syncFloors: false });
                if (labelWallHeight) labelWallHeight.textContent = `${originalHeight.toFixed(1)} m`;
            }
        });
    }

    if (chkWalls) chkWalls.addEventListener("change", (e) => viewer?.toggleLayer("walls", e.target.checked));
    if (chkFloors) chkFloors.addEventListener("change", (e) => viewer?.toggleLayer("rooms", e.target.checked));
    if (chkRoof) chkRoof.addEventListener("change", (e) => viewer?.toggleLayer("roof", e.target.checked));
    if (chkLabels) chkLabels.addEventListener("change", (e) => viewer?.toggleLayer("labels", e.target.checked));
    if (chkOpenings) chkOpenings.addEventListener("change", (e) => {
        viewer?.toggleLayer("doors", e.target.checked);
        viewer?.toggleLayer("windows", e.target.checked);
    });
    if (chkGrid) chkGrid.addEventListener("change", (e) => viewer?.toggleLayer("grid", e.target.checked));
    if (chkFurniture) chkFurniture.addEventListener("change", (e) => viewer?.toggleLayer("furniture", e.target.checked));

    if (btnWalkthrough) {
        btnWalkthrough.addEventListener("click", () => {
            if (!viewer) return;
            const enabled = viewer.toggleWalkthroughMode();
            btnWalkthrough.setAttribute("aria-pressed", String(enabled));
            btnWalkthrough.textContent = enabled ? "Exit Walkthrough" : "Walkthrough";
        });
    }
    viewer.onWalkthroughChange = enabled => {
        btnWalkthrough.setAttribute("aria-pressed", String(enabled));
        btnWalkthrough.textContent = enabled ? "Exit Walkthrough" : "Walkthrough";
    };
    viewer.onWalkthroughStoryViewChange = value => { levelFilter.value = value; };

    const btnWalkOutside = document.getElementById("btn-walk-outside");
    const btnWalkInside = document.getElementById("btn-walk-inside");
    if (btnWalkOutside) {
        btnWalkOutside.addEventListener("click", () => {
            if (viewer) viewer.walkOutside();
        });
    }
    if (btnWalkInside) {
        btnWalkInside.addEventListener("click", () => {
            if (viewer) viewer.walkInside();
        });
    }
    if (btnMeasure) {
        btnMeasure.addEventListener("click", () => {
            if (!viewer) return;
            const enabled = viewer.toggleMeasurementMode();
            btnMeasure.setAttribute("aria-pressed", String(enabled));
            btnMeasure.textContent = enabled ? "Stop Measure" : "Measure";
            if (measurementPanel) measurementPanel.classList.toggle("hidden", !enabled);
            if (measurementStatus) measurementStatus.textContent = enabled ? "Click a first point in the 3D view." : "Measurement stopped.";
        });
    }
    if (btnClearMeasurement) {
        btnClearMeasurement.addEventListener("click", () => {
            if (viewer) viewer.clearMeasurement();
            if (measurementStatus) measurementStatus.textContent = "Click a first point to measure.";
        });
    }
    if (viewer) {
        viewer.onMeasurementUpdate = message => { if (measurementStatus) measurementStatus.textContent = message; };
        viewer.onMeasurementModeChange = enabled => {
            if (btnMeasure) {
                btnMeasure.setAttribute("aria-pressed", String(enabled));
                btnMeasure.textContent = enabled ? "Stop Measure" : "Measure";
            }
            if (measurementPanel) measurementPanel.classList.toggle("hidden", !enabled);
        };
    }

    if (btnCalibrateScale) {
        btnCalibrateScale.addEventListener("click", () => {
            if (!currentSceneData || !loadedImageElement) {
                if (scaleCalibrationStatus) scaleCalibrationStatus.textContent = "Load a floor plan before calibrating scale.";
                return;
            }
            scaleCalibrationActive = true;
            scaleCalibrationPoints = [];
            btnCalibrateScale.setAttribute("aria-pressed", "true");
            btnCalibrateScale.classList.add("calibration-active");
            if (btnApplyScale) btnApplyScale.disabled = true;
            if (scaleCalibrationStatus) scaleCalibrationStatus.textContent = "Click the first point, then the second point on the plan.";
            if (segmentationCanvas) segmentationCanvas.classList.add("calibration-crosshair");
        });
    }

    segmentationCanvas.addEventListener("click", event => {
        if (!scaleCalibrationActive) return;
        const rect = segmentationCanvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        scaleCalibrationPoints.push([
            (event.clientX - rect.left) * segmentationCanvas.width / rect.width,
            (event.clientY - rect.top) * segmentationCanvas.height / rect.height,
        ]);
        if (scaleCalibrationPoints.length === 1) {
            scaleCalibrationStatus.textContent = "First point set. Click the second point.";
            render2DSegmentationCanvas();
            return;
        }
        scaleCalibrationActive = false;
        segmentationCanvas.classList.remove("calibration-crosshair");
        btnCalibrateScale.setAttribute("aria-pressed", "false");
        btnCalibrateScale.classList.remove("calibration-active");
        btnApplyScale.disabled = false;
        scaleCalibrationStatus.textContent = `Points selected (${Math.hypot(scaleCalibrationPoints[1][0] - scaleCalibrationPoints[0][0], scaleCalibrationPoints[1][1] - scaleCalibrationPoints[0][1]).toFixed(1)} px). Enter the known length and apply.`;
        render2DSegmentationCanvas();
    });

    function setOpeningEditMode(mode) {
        openingEditMode = mode;
        selectedOpening = null;
        if (btnDeleteOpening2D) btnDeleteOpening2D.disabled = true;
        [[btnAddDoor2D, "add-door"], [btnAddWindow2D, "add-window"]].forEach(([button, buttonMode]) => {
            if (!button) return;
            const active = mode === buttonMode;
            button.setAttribute("aria-pressed", String(active));
            button.classList.toggle("calibration-active", active);
        });
        if (segmentationCanvas) segCtx.canvas.style.cursor = mode ? "crosshair" : "";
        if (!openingEditStatus) return;
        openingEditStatus.textContent = mode === "add-door"
            ? "Click the source plan on a wall to add a 0.9 m door."
            : mode === "add-window"
                ? "Click the source plan on an exterior wall to add a 1.2 m window."
                : "Select an opening to delete it, or add one on a wall. Geometry rebuilds locally; SAM is not called again.";
        render2DSegmentationCanvas();
    }

    btnAddDoor2D?.addEventListener("click", () => {
        if (!currentSceneData) return showMessage("Load a floor plan before adding a door.", "info");
        setOpeningEditMode(openingEditMode === "add-door" ? null : "add-door");
    });
    btnAddWindow2D?.addEventListener("click", () => {
        if (!currentSceneData) return showMessage("Load a floor plan before adding a window.", "info");
        setOpeningEditMode(openingEditMode === "add-window" ? null : "add-window");
    });

    segmentationCanvas.addEventListener("click", event => {
        if (!currentSceneData || scaleCalibrationActive || polygonEditActive || !loadedImageElement) return;
        const rect = segmentationCanvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const sourcePixels = [
            (event.clientX - rect.left) * segmentationCanvas.width / rect.width,
            (event.clientY - rect.top) * segmentationCanvas.height / rect.height,
        ];

        if (openingEditMode === "add-door" || openingEditMode === "add-window") {
            const kind = openingEditMode === "add-door" ? "door" : "window";
            const floorIndex = levelFilter.value === "all" ? 0 : Number(levelFilter.value);
            const candidate = JSON.parse(JSON.stringify(currentSceneData));
            const collection = kind === "door" ? "doors" : "windows";
            candidate[collection] ||= [];
            let number = 1;
            const prefix = kind === "door" ? "manual_d" : "manual_win";
            const ids = new Set(candidate[collection].map(item => item.id));
            while (ids.has(`${prefix}${number}`)) number += 1;
            const item = {
                id: `${prefix}${number}`,
                center: sourcePixelsToScenePoint(sourcePixels, floorIndex),
                width: kind === "door" ? 0.9 : 1.2,
                floorIndex,
                level: floorIndex,
                source: "manual",
            };
            if (kind === "door") item.connects = [];
            candidate[collection].push(item);
            setOpeningEditMode(null);
            rebuildEditedGeometry(candidate, `${kind === "door" ? "Door" : "Window"} added and wall geometry rebuilt locally.`);
            return;
        }

        const allowedFloors = levelFilter.value === "all" ? null : Number(levelFilter.value);
        const candidates = [
            ...(currentSceneData.doors || []).map(item => ({ kind: "door", item })),
            ...(currentSceneData.windows || []).map(item => ({ kind: "window", item })),
        ].filter(entry => allowedFloors === null || entityFloorIndex(entry.item) === allowedFloors);
        let nearest = null;
        for (const entry of candidates) {
            const source = scenePointToSourcePixels(entry.item, entry.item.center || [0, 0]);
            const distance = Math.hypot(sourcePixels[0] - source[0], sourcePixels[1] - source[1]);
            const widthPx = (Number(entry.item.width) || (entry.kind === "door" ? 0.9 : 1.2)) / scaleForLevel(entityFloorIndex(entry.item));
            const hitRadius = Math.max(16, Math.min(48, widthPx / 2 + 8));
            if (distance <= hitRadius && (!nearest || distance < nearest.distance)) nearest = { ...entry, distance };
        }
        selectedOpening = nearest ? { kind: nearest.kind, id: nearest.item.id } : null;
        if (btnDeleteOpening2D) btnDeleteOpening2D.disabled = !selectedOpening;
        if (openingEditStatus) openingEditStatus.textContent = selectedOpening
            ? `Selected ${selectedOpening.kind} ${selectedOpening.id}. Use Delete selected or press Delete.`
            : "No opening selected. Click a door or window marker to select it.";
        render2DSegmentationCanvas();
    });

    btnDeleteOpening2D?.addEventListener("click", () => {
        if (!currentSceneData || !selectedOpening) return;
        const candidate = JSON.parse(JSON.stringify(currentSceneData));
        const collection = selectedOpening.kind === "door" ? "doors" : "windows";
        candidate[collection] = (candidate[collection] || []).filter(item => item.id !== selectedOpening.id);
        rebuildEditedGeometry(candidate, `${selectedOpening.kind === "door" ? "Door" : "Window"} deleted and wall geometry rebuilt locally.`);
    });

    document.addEventListener("keydown", event => {
        const focused = document.activeElement;
        if ((event.key === "Delete" || event.key === "Backspace")
            && selectedOpening
            && !focused?.matches("input, textarea, select, [contenteditable='true']")
            && btnDeleteOpening2D && !btnDeleteOpening2D.disabled) {
            event.preventDefault();
            btnDeleteOpening2D.click();
        }
    });

    if (btnEditBoundary) {
        btnEditBoundary.addEventListener("click", () => {
            const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
            if (!room || !loadedImageElement || (room.polygon || []).length < 3) {
                if (boundaryEditStatus) boundaryEditStatus.textContent = "Select a room with a valid outline and its plan image first.";
                return;
            }
            polygonEditActive = true;
            if (segmentationCanvas) segmentationCanvas.classList.add("polygon-edit-active");
            polygonEditUndoStack = [];
            polygonEditDragIndex = null;
            if (boundaryEditControls) boundaryEditControls.classList.remove("hidden");
            if (boundaryEditStatus) boundaryEditStatus.textContent = "Open 2D Segmentation, then drag a cyan vertex to adjust the outline.";
            if (viewer) viewer.previewRoomBoundary(room);
            const tab2d = document.querySelector('[data-tab="2d"]');
            if (tab2d) tab2d.click();
            render2DSegmentationCanvas();
        });
    }

    if (btnBoundaryUndo) {
        btnBoundaryUndo.addEventListener("click", () => {
            const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
            const previous = polygonEditUndoStack.pop();
            if (!room || !previous) return;
            room.polygon = previous;
            btnBoundaryUndo.disabled = polygonEditUndoStack.length === 0;
            if (boundaryEditStatus) boundaryEditStatus.textContent = "Previous outline restored.";
            refreshBoundaryScene();
        });
    }

    if (btnBoundaryDone) {
        btnBoundaryDone.addEventListener("click", () => {
            polygonEditActive = false;
            if (segmentationCanvas) segmentationCanvas.classList.remove("polygon-edit-active");
            polygonEditDragIndex = null;
            if (boundaryEditControls) boundaryEditControls.classList.add("hidden");
            if (viewer) viewer.clearRoomBoundaryPreview();
            if (boundaryEditStatus) boundaryEditStatus.textContent = "Outline saved and shown on the 3D floor. The cyan edge marks the edit; detected wall solids are a separate geometry layer. Export scene.json or GLB to keep it.";
            render2DSegmentationCanvas();
        });
    }

    segmentationCanvas.addEventListener("pointerdown", event => {
        if (!polygonEditActive || scaleCalibrationActive || !selectedRoomId) return;
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        if (!room || (room.polygon || []).length < 3) return;
        const rect = segmentationCanvas.getBoundingClientRect();
        const x = (event.clientX - rect.left) * segmentationCanvas.width / rect.width;
        const y = (event.clientY - rect.top) * segmentationCanvas.height / rect.height;
        const hitRadius = Math.max(12, Math.min(28, segmentationCanvas.width * 0.025));
        let bestIndex = -1;
        let bestDistance = hitRadius;
        room.polygon.forEach((point, index) => {
            const source = scenePointToSourcePixels(room, point);
            const distance = Math.hypot(source[0] - x, source[1] - y);
            if (distance < bestDistance) { bestIndex = index; bestDistance = distance; }
        });
        if (bestIndex < 0) {
            boundaryEditStatus.textContent = "Drag a cyan vertex handle; new vertices are not added in this editor.";
            return;
        }
        polygonEditUndoStack.push(room.polygon.map(point => [...point]));
        btnBoundaryUndo.disabled = false;
        polygonEditDragIndex = bestIndex;
        segmentationCanvas.setPointerCapture(event.pointerId);
        event.preventDefault();
    });

    segmentationCanvas.addEventListener("pointermove", event => {
        if (polygonEditDragIndex === null || !polygonEditActive) return;
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        if (!room) return;
        const rect = segmentationCanvas.getBoundingClientRect();
        const candidate = room.polygon.map(point => [...point]);
        const sourcePoint = [
            Math.max(0, (event.clientX - rect.left) * segmentationCanvas.width / rect.width),
            Math.max(0, (event.clientY - rect.top) * segmentationCanvas.height / rect.height),
        ];
        candidate[polygonEditDragIndex] = sourcePixelsToScenePoint(sourcePoint, entityFloorIndex(room));
        if (polygonArea(candidate) < 0.05 || polygonHasSelfIntersection(candidate)) {
            boundaryEditStatus.textContent = "That move would make the room outline invalid. Try another position.";
            return;
        }
        room.polygon = candidate;
        viewer.previewRoomBoundary(room);
        boundaryEditStatus.textContent = `Moving vertex ${polygonEditDragIndex + 1} of ${room.polygon.length}.`;
        render2DSegmentationCanvas();
    });

    const finishBoundaryDrag = () => {
        if (polygonEditDragIndex === null) return;
        polygonEditDragIndex = null;
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        if (room) {
            boundaryEditStatus.textContent = "Outline updated on the 3D floor. The cyan edge marks the edit; detected wall solids are a separate geometry layer.";
            refreshBoundaryScene();
        }
    };
    segmentationCanvas.addEventListener("pointerup", finishBoundaryDrag);
    segmentationCanvas.addEventListener("pointercancel", finishBoundaryDrag);

    if (btnCancelScale) {
        btnCancelScale.addEventListener("click", () => {
            scaleCalibrationActive = false;
            scaleCalibrationPoints = [];
            if (btnApplyScale) btnApplyScale.disabled = true;
            if (btnCalibrateScale) {
                btnCalibrateScale.setAttribute("aria-pressed", "false");
                btnCalibrateScale.classList.remove("calibration-active");
            }
            if (segmentationCanvas) segmentationCanvas.classList.remove("calibration-crosshair");
            if (scaleCalibrationStatus) scaleCalibrationStatus.textContent = "Scale calibration cancelled.";
            if (loadedImageElement) render2DSegmentationCanvas();
        });
    }

    btnApplyScale.addEventListener("click", () => {
        const knownMeters = Number(knownLength.value);
        const [first, second] = scaleCalibrationPoints;
        if (!currentSceneData || !first || !second || !Number.isFinite(knownMeters) || knownMeters <= 0) {
            scaleCalibrationStatus.textContent = "Choose two points and enter a positive known length.";
            return;
        }
        const pixelDistance = Math.hypot(second[0] - first[0], second[1] - first[1]);
        if (pixelDistance < 1) {
            scaleCalibrationStatus.textContent = "The selected points are too close together.";
            return;
        }
        const newScale = knownMeters / pixelDistance;
        if ((currentSceneData.meta.levels || []).length > 1) {
            const levelIndex = levelFilter.value === "all" ? 0 : Number(levelFilter.value);
            const levelInfo = (currentSceneData.meta.levels || []).find(level => Number(level.level ?? level.floorIndex) === levelIndex);
            if (!levelInfo) {
                scaleCalibrationStatus.textContent = "Choose a story before calibrating its scale.";
                return;
            }
            const previousScale = Number(levelInfo.metersPerPixel) || Number(currentSceneData.meta.metersPerPixel) || 0.02;
            const factor = newScale / previousScale;
            const oldAnchor = levelInfo.planAnchor || [0, 0];
            const oldOffset = levelInfo.planOffset || [0, 0];
            const rootLevel = currentSceneData.meta.levels.find(level => Number(level.level ?? level.floorIndex) === 0) || levelInfo;
            const rootAnchor = [
                (Number(rootLevel.planAnchor?.[0]) || 0) + (Number(rootLevel.planOffset?.[0]) || 0),
                (Number(rootLevel.planAnchor?.[1]) || 0) + (Number(rootLevel.planOffset?.[1]) || 0),
            ];
            const previousTarget = [oldAnchor[0] + oldOffset[0], oldAnchor[1] + oldOffset[1]];
            const targetAnchor = levelIndex === 0
                ? [previousTarget[0] * factor, previousTarget[1] * factor]
                : rootAnchor;
            const transformPoint = point => [
                targetAnchor[0] + (point[0] - oldOffset[0] - oldAnchor[0]) * factor,
                targetAnchor[1] + (point[1] - oldOffset[1] - oldAnchor[1]) * factor,
            ];
            const belongs = item => Number(item.level ?? item.floorIndex) === levelIndex;
            currentSceneData.rooms.filter(belongs).forEach(room => {
                room.polygon = (room.polygon || []).map(transformPoint);
                room.holes = (room.holes || []).map(polygon => polygon.map(transformPoint));
                if (room.centroid) room.centroid = transformPoint(room.centroid);
                if (Number.isFinite(Number(room.area_m2))) room.area_m2 *= factor * factor;
            });
            currentSceneData.walls.filter(belongs).forEach(wall => {
                wall.polygon = (wall.polygon || []).map(transformPoint);
                wall.holes = (wall.holes || []).map(polygon => polygon.map(transformPoint));
            });
            ["doors", "windows"].forEach(collection => (currentSceneData[collection] || []).filter(belongs).forEach(item => {
                if (item.center) item.center = transformPoint(item.center);
                item.width *= factor;
            }));
            levelInfo.planAnchor = [oldAnchor[0] * factor, oldAnchor[1] * factor];
            levelInfo.planOffset = [targetAnchor[0] - levelInfo.planAnchor[0], targetAnchor[1] - levelInfo.planAnchor[1]];
            levelInfo.metersPerPixel = newScale;
            levelInfo.scaleSource = "user";
            levelInfo.scaleConfidence = 1.0;
            if (levelIndex === 0) {
                const shift = [targetAnchor[0] - previousTarget[0], targetAnchor[1] - previousTarget[1]];
                const shiftPoint = point => [point[0] + shift[0], point[1] + shift[1]];
                currentSceneData.meta.levels.filter(level => Number(level.level ?? level.floorIndex) !== 0).forEach(level => {
                    const otherIndex = Number(level.level ?? level.floorIndex);
                    const isOtherFloor = item => Number(item.level ?? item.floorIndex) === otherIndex;
                    currentSceneData.rooms.filter(isOtherFloor).forEach(room => {
                        room.polygon = (room.polygon || []).map(shiftPoint);
                        room.holes = (room.holes || []).map(polygon => polygon.map(shiftPoint));
                        if (room.centroid) room.centroid = shiftPoint(room.centroid);
                    });
                    currentSceneData.walls.filter(isOtherFloor).forEach(wall => {
                        wall.polygon = (wall.polygon || []).map(shiftPoint);
                        wall.holes = (wall.holes || []).map(polygon => polygon.map(shiftPoint));
                    });
                    ["doors", "windows"].forEach(collection => (currentSceneData[collection] || []).filter(isOtherFloor).forEach(item => {
                        if (item.center) item.center = shiftPoint(item.center);
                    }));
                    level.planOffset = [level.planOffset[0] + shift[0], level.planOffset[1] + shift[1]];
                });
                currentSceneData.meta.metersPerPixel = newScale;
            }
            currentSceneData.meta.scaleMethod = `interactive two-point calibration on story ${levelIndex + 1}`;
            const allLevelsCalibrated = currentSceneData.meta.levels.every(level => String(level.scaleSource || "needs-review") !== "needs-review");
            currentSceneData.meta.scaleSource = allLevelsCalibrated
                ? (currentSceneData.meta.levels.every(level => level.scaleSource === "user") ? "user" : "mixed")
                : "needs-review";
            currentSceneData.meta.scaleConfidence = Math.min(...currentSceneData.meta.levels.map(level => Number(level.scaleConfidence) || 0));
            currentSceneData.meta.warnings = [...new Set([...(currentSceneData.meta.warnings || []), `Story ${levelIndex + 1} scale was recalibrated from two user-selected points and a known length.`])];
            labelMpp.textContent = `${newScale.toFixed(4)} m/px`;
            overlayScale.textContent = `Scale: ${newScale.toFixed(4)} m/px`;
            inputMpp.min = String(Math.min(0.005, newScale));
            inputMpp.max = String(Math.max(0.08, newScale));
            inputMpp.value = String(newScale);
            scaleCalibrationPoints = [];
            btnApplyScale.disabled = true;
            scaleCalibrationStatus.textContent = `Story ${levelIndex + 1} scale updated to ${newScale.toFixed(5)} m/px.`;
            rebuildEditedGeometry(JSON.parse(JSON.stringify(currentSceneData)), `Story ${levelIndex + 1} scale saved; review checks were recalculated.`);
            return;
        }
        const previousScale = Number(currentSceneData.meta.metersPerPixel) || 0.02;
        const factor = newScale / previousScale;
        const scalePoints = points => (points || []).map(([x, y]) => [x * factor, y * factor]);
        currentSceneData.rooms.forEach(room => {
            room.polygon = scalePoints(room.polygon);
            room.holes = (room.holes || []).map(scalePoints);
            if (room.centroid) room.centroid = [room.centroid[0] * factor, room.centroid[1] * factor];
            if (Number.isFinite(Number(room.area_m2))) room.area_m2 *= factor * factor;
        });
        currentSceneData.walls.forEach(wall => {
            wall.polygon = scalePoints(wall.polygon);
            wall.holes = (wall.holes || []).map(scalePoints);
        });
        ["doors", "windows"].forEach(collection => (currentSceneData[collection] || []).forEach(item => {
            item.center = [item.center[0] * factor, item.center[1] * factor];
            item.width *= factor;
        }));
        currentSceneData.meta.metersPerPixel = newScale;
        currentSceneData.meta.scaleMethod = "interactive two-point calibration";
        currentSceneData.meta.scaleSource = "user";
        currentSceneData.meta.scaleConfidence = 1.0;
        const groundLevel = (currentSceneData.meta.levels || []).find(level => Number(level.level ?? level.floorIndex) === 0);
        if (groundLevel) {
            groundLevel.metersPerPixel = newScale;
            groundLevel.scaleSource = "user";
            groundLevel.scaleConfidence = 1.0;
        }
        currentSceneData.meta.warnings = [...new Set([...(currentSceneData.meta.warnings || []), "Scale was recalibrated from two user-selected points and a known length."])];
        inputMpp.min = String(Math.min(0.005, newScale));
        inputMpp.max = String(Math.max(0.08, newScale));
        inputMpp.value = String(newScale);
        labelMpp.textContent = `${newScale.toFixed(4)} m/px`;
        overlayScale.textContent = `Scale: ${newScale.toFixed(4)} m/px`;
        scaleCalibrationPoints = [];
        btnApplyScale.disabled = true;
        scaleCalibrationStatus.textContent = `Scale updated to ${newScale.toFixed(5)} m/px.`;
        rebuildEditedGeometry(JSON.parse(JSON.stringify(currentSceneData)), "Scale saved; review checks were recalculated.");
    });

    // -------------------------------------------------------------
    // Tab Navigation
    // -------------------------------------------------------------
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            
            tabBtns.forEach(b => {
                b.classList.remove("active", "border-blue-500", "text-blue-400");
                b.classList.add("border-transparent", "text-slate-400");
            });
            btn.classList.add("active", "border-blue-500", "text-blue-400");
            btn.classList.remove("border-transparent", "text-slate-400");

            tabPanels.forEach(panel => {
                if (panel.id === `tab-${targetTab}`) {
                    panel.classList.remove("hidden");
                } else {
                    panel.classList.add("hidden");
                }
            });

            // If switching to 3D tab, trigger resize so Three.js renders correctly
            const viewportControls = document.getElementById("viewport-controls");
            if (viewportControls) viewportControls.classList.toggle("hidden", targetTab !== "3d");
            if (targetTab === "3d") {
                viewer.onWindowResize();
            } else if (targetTab === "2d") {
                render2DSegmentationCanvas();
            }
        });
    });

    // -------------------------------------------------------------
    // Load Demo Hackathon Floor Plan
    // -------------------------------------------------------------
    if (btnLoadDemo) btnLoadDemo.addEventListener("click", async () => {
        try {
            btnLoadDemo.disabled = true;
            btnLoadDemo.textContent = "Loading Demo...";
            viewer.showLoadingState();

            const res = await fetch("/api/sample");
            const data = await res.json();

            if (!data.success) {
                throw new Error(data.error || "Failed to load demo floor plan.");
            }
            clearMessage();

            // Update UI with demo data
            imagePreview.src = data.imageUrl;
            imagePreviewContainer.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");

            // Load into 3D viewer
            handleProcessSuccess(data);
            showMessage("Loaded the prepared sample scene. No live AI inference was run.");

        } catch (err) {
            viewer.hideLoadingState();
            alert(`Demo load error: ${err.message}`);
        } finally {
            btnLoadDemo.disabled = false;
            btnLoadDemo.textContent = "Load Hackathon Demo Plan";
        }
    });

    if (btnLoadTwoStoryDemo) btnLoadTwoStoryDemo.addEventListener("click", async () => {
        try {
            viewer.showLoadingState();
            btnLoadTwoStoryDemo.disabled = true;
            btnLoadTwoStoryDemo.textContent = "Loading Two-Story Demo...";

            const response = await fetch("/api/sample/two-story");
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to load the two-story demo.");
            }

            clearMessage();
            imagePreview.src = data.imageUrl;
            imagePreviewContainer.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");
            handleProcessSuccess(data);
            showMessage("Loaded the prepared two-story building. Use the story selector to inspect each level.");
        } catch (err) {
            viewer.hideLoadingState();
            alert(`Two-story demo load error: ${err.message}`);
        } finally {
            btnLoadTwoStoryDemo.disabled = false;
            btnLoadTwoStoryDemo.textContent = "Load Two-Story Demo";
        }
    });

    // -------------------------------------------------------------
    // Process uploads through a real job/status API.
    // -------------------------------------------------------------
    if (btnGenerate) btnGenerate.addEventListener("click", async () => {
        if (!selectedFile) {
            alert("Please select a floor plan image first.");
            return;
        }

        btnGenerate.disabled = true;
        progressContainer.classList.remove("hidden");
        viewer.showLoadingState();

        try {
            const formData = new FormData();
            formData.append("file", selectedFile);
            formData.append("metersPerPixel", inputMpp.value);
            formData.append("calibrateScale", chkAutoScale.checked ? "true" : "false");
            formData.append("scaleSource", uploadScaleSource);
            formData.append("wallHeight", inputWallHeight.value);
            formData.append("wallThickness", inputWallThickness.value);
            const floorCount = Number(inputFloorCount?.value) || 1;
            formData.append("floorCount", String(floorCount));
            formData.append("splitOrientation", inputSplitOrientation?.value || "vertical");
            if (floorCount >= 2) formData.append("splitPosition1", String((Number(inputSplitPosition1.value) || 50) / 100));
            if (floorCount >= 3) formData.append("splitPosition2", String((Number(inputSplitPosition2.value) || 67) / 100));

            progressStatus.textContent = "Uploading floor plan…";
            progressBar.style.width = "5%";
            const response = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });

            const startData = await response.json();
            if (!response.ok || !startData.success) {
                throw new Error(startData.error || "Could not start processing.");
            }

            let jobStatus;
            const processingDeadline = Date.now() + 7 * 60 * 1000;
            while (true) {
                if (Date.now() > processingDeadline) throw new Error("Processing is taking longer than expected. You can keep using the prepared demo and check the provider setup later.");
                await new Promise(resolve => setTimeout(resolve, 800));
                const statusResponse = await fetch(`/api/status/${encodeURIComponent(startData.job_id)}`);
                jobStatus = await statusResponse.json();
                if (!statusResponse.ok) throw new Error(jobStatus.error || "Could not read processing status.");
                progressBar.style.width = `${Math.max(5, Math.min(100, jobStatus.progress || 5))}%`;
                progressStatus.textContent = jobStatus.stage || "Processing floor plan…";
                if (jobStatus.status === "failed") throw new Error(jobStatus.error || "Processing failed.");
                if (jobStatus.status === "complete") break;
            }

            const sceneResponse = await fetch(`/api/scene/${encodeURIComponent(startData.job_id)}`);
            const data = await sceneResponse.json();
            if (!sceneResponse.ok) throw new Error(data.error || "The scene could not be loaded.");

            handleProcessSuccess(data);
            progressBar.style.width = "100%";
            progressStatus.textContent = "3D map ready";
            if (data.scene.meta.processingMode === "MOCK") {
                showMessage("MOCK MODE completed from the prepared sample plan. Your uploaded image was not analyzed and no live AI inference ran.", "warning");
            } else if (data.scene.meta.warnings && data.scene.meta.warnings.length) {
                showMessage(data.scene.meta.warnings.join(" "), "warning");
            } else {
                showMessage("Floor plan processed. Local OpenCV fallback was used where Meta segmentation was unavailable; room labels may be generic.");
            }
            setTimeout(() => {
                progressContainer.classList.add("hidden");
                progressBar.style.width = "0%";
            }, 1200);

        } catch (err) {
            viewer.hideLoadingState();
            progressContainer.classList.add("hidden");
            progressBar.style.width = "0%";
            showMessage(err.message || "Could not process this floor plan.", "error");
        } finally {
            btnGenerate.disabled = !processingReady || !selectedFile;
        }
    });

    async function processUploadedPlan(file, reportProgress) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("metersPerPixel", inputMpp.value);
        formData.append("calibrateScale", chkAutoScale.checked ? "true" : "false");
        formData.append("wallHeight", inputWallHeight.value);
        formData.append("wallThickness", inputWallThickness.value);
        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const started = await response.json();
        if (!response.ok || !started.success) throw new Error(started.error || "Could not start plan processing.");
        const deadline = Date.now() + 7 * 60 * 1000;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, 800));
            const statusResponse = await fetch(`/api/status/${encodeURIComponent(started.job_id)}`);
            const status = await statusResponse.json();
            if (!statusResponse.ok) throw new Error(status.error || "Could not read plan status.");
            reportProgress(status.stage || "Processing floor plan…", status.progress || 5);
            if (status.status === "failed") throw new Error(status.error || "Plan processing failed.");
            if (status.status === "complete") {
                const resultResponse = await fetch(`/api/scene/${encodeURIComponent(started.job_id)}`);
                const result = await resultResponse.json();
                if (!resultResponse.ok) throw new Error(result.error || "The processed scene could not be loaded.");
                return result.scene;
            }
        }
        throw new Error("Processing exceeded the seven-minute time limit.");
    }

    function planAnchor(scene) {
        const rooms = scene.rooms || [];
        const stair = rooms.find(room => ["stairs", "stair", "elevator"].includes(String(room.type || "").toLowerCase()));
        const connectorPoints = stair?.polygon || [];
        if (connectorPoints.length) return connectorPoints.reduce((sum, point) => [sum[0] + point[0] / connectorPoints.length, sum[1] + point[1] / connectorPoints.length], [0, 0]);
        const points = rooms.flatMap(room => room.polygon || []);
        if (!points.length) return [0, 0];
        const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
        return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
    }

    function combineFloorScenes(scenes) {
        const baseAnchor = planAnchor(scenes[0]);
        const hasConnector = scene => (scene.rooms || []).some(room => ["stairs", "stair", "elevator"].includes(String(room.type || "").toLowerCase()));
        const connectorLevels = scenes.map((scene, index) => hasConnector(scene) ? index : null).filter(index => index !== null);
        const floorHeight = Math.max(2.5, Number(scenes[0].meta?.wallHeight) || Number(inputWallHeight.value) || 3.0);
        const merged = {
            meta: {
                ...scenes[0].meta,
                source: "multi_floor_upload",
                levelCount: scenes.length,
                floorHeight,
                levels: scenes.map((scene, level) => ({
                    level,
                    name: level === 0 ? "Ground Floor" : `Floor ${level + 1}`,
                    elevation: level * floorHeight,
                    metersPerPixel: Number(scene.meta?.metersPerPixel) || 0.02,
                    imageSize: scene.meta?.imageSize || [1, 1],
                    alignmentMethod: hasConnector(scene) ? "connector-centroid" : "plan-bounds-center",
                    planOffset: [baseAnchor[0] - planAnchor(scene)[0], baseAnchor[1] - planAnchor(scene)[1]],
                    planAnchor: planAnchor(scene),
                })),
                warnings: [...new Set(scenes.flatMap(scene => scene.meta?.warnings || []))],
            },
            rooms: [], walls: [], doors: [], windows: [],
        };
        const collections = ["rooms", "walls", "doors", "windows"];
        scenes.forEach((scene, level) => {
            const anchor = planAnchor(scene);
            const delta = [baseAnchor[0] - anchor[0], baseAnchor[1] - anchor[1]];
            const idMap = new Map();
            (scene.rooms || []).forEach(item => idMap.set(item.id, `${item.id}_floor${level + 1}`));
            collections.forEach(collection => {
                (scene[collection] || []).forEach(original => {
                    const item = JSON.parse(JSON.stringify(original));
                    item.id = `${original.id}_floor${level + 1}`;
                    item.level = level;
                    item.floorIndex = level;
                    if (Array.isArray(item.polygon)) item.polygon = item.polygon.map(point => [point[0] + delta[0], point[1] + delta[1]]);
                    if (Array.isArray(item.holes)) item.holes = item.holes.map(polygon => polygon.map(point => [point[0] + delta[0], point[1] + delta[1]]));
                    if (Array.isArray(item.center)) item.center = [item.center[0] + delta[0], item.center[1] + delta[1]];
                    if (Array.isArray(item.centroid)) item.centroid = [item.centroid[0] + delta[0], item.centroid[1] + delta[1]];
                    if (Array.isArray(item.connects)) item.connects = item.connects.map(id => idMap.get(id) || id);
                    merged[collection].push(item);
                });
            });
        });
        if (connectorLevels.length === scenes.length) {
            merged.meta.warnings.push("Stories were automatically aligned by detected stair/elevator room centroids. Verify alignment against the building drawings before relying on cross-floor measurements or routes.");
        } else if (connectorLevels.length) {
            const missingLevels = scenes.map((_scene, index) => index).filter(index => !connectorLevels.includes(index)).map(index => index + 1);
            merged.meta.warnings.push(`Stories with detected stair/elevator rooms were aligned by their centroids; floor(s) ${missingLevels.join(", ")} used plan-bound centers. Verify connector alignment before relying on cross-floor routes or measurements.`);
        } else {
            merged.meta.warnings.push("No stair/elevator room was detected. Stories were centered by plan bounds; no vertical connector relationship was inferred. Verify alignment before relying on cross-floor routes or measurements.");
        }
        const modes = scenes.map(scene => String(scene.meta?.processingMode || "OFFLINE").toUpperCase());
        merged.meta.processingMode = modes.includes("MOCK") ? "MOCK"
            : modes.every(mode => mode === "DEMO") ? "DEMO" : "LOCAL";
        return merged;
    }

    function readAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
            reader.readAsDataURL(file);
        });
    }

    async function loadImageElement(source) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => reject(new Error("Could not display one of the selected floor plan images."));
            image.src = source;
        });
    }

    if (btnProcessBuilding) btnProcessBuilding.addEventListener("click", async () => {
        if (selectedFiles.length < 2) return;
        btnProcessBuilding.disabled = true;
        btnGenerate.disabled = true;
        progressContainer.classList.remove("hidden");
        viewer.showLoadingState();
        try {
            const scenes = [];
            for (let index = 0; index < selectedFiles.length; index++) {
                progressStatus.textContent = `Floor ${index + 1} of ${selectedFiles.length}: uploading…`;
                buildingUploadStatus.textContent = `Processing ${index + 1}/${selectedFiles.length}: ${selectedFiles[index].name}`;
                const scene = await processUploadedPlan(selectedFiles[index], (stage, percent) => {
                    progressStatus.textContent = `Floor ${index + 1}/${selectedFiles.length}: ${stage}`;
                    progressBar.style.width = `${Math.round(((index + percent / 100) / selectedFiles.length) * 100)}%`;
                });
                scenes.push(scene);
            }
            const floorImagesData = await Promise.all(selectedFiles.map(readAsDataUrl));
            const floorImages = await Promise.all(floorImagesData.map(loadImageElement));
            const scene = combineFloorScenes(scenes);
            handleProcessSuccess({ scene, imageUrl: floorImagesData[0], floorImages });
            levelFilter.value = "0";
            viewer.setVisibleLevel("0");
            loadedImageElement = floorImages[0];
            render2DSegmentationCanvas();
            progressBar.style.width = "100%";
            progressStatus.textContent = "Multi-floor building ready";
            const mode = scene.meta.processingMode;
            const modeMessage = mode === "MOCK"
                ? "MOCK MODE: at least one story uses prepared sample geometry, not uploaded-image analysis. Verify connector alignment."
                : mode === "DEMO"
                    ? "Prepared demo stories loaded. Verify stair alignment before relying on measurements."
                    : "Stories were segmented locally with OpenCV. Verify stair alignment and scale before relying on measurements.";
            showMessage(modeMessage, "warning");
            buildingUploadStatus.textContent = "Stories aligned. Check each floor in the selector and verify stair/elevator alignment.";
        } catch (error) {
            viewer.hideLoadingState();
            showMessage(error.message || "Could not process the selected building plans.", "error");
            buildingUploadStatus.textContent = error.message || "Could not process the selected plans.";
        } finally {
            btnProcessBuilding.disabled = !processingReady || selectedFiles.length < 2;
            btnGenerate.disabled = !processingReady || !selectedFile;
            window.setTimeout(() => {
                progressContainer.classList.add("hidden");
                progressBar.style.width = "0%";
            }, 1200);
        }
    });

    function handleProcessSuccess(data) {
        currentSceneData = data.scene;
        window.currentSceneData = currentSceneData;
        floorPlanImages = Array.isArray(data.floorImages) ? data.floorImages : [];
        const sceneMeta = currentSceneData.meta || {};
        const needsReview = Boolean(sceneMeta.needsReview);
        const isSavedSample = Boolean(sceneMeta.preparedSample);
        setProcessingBadge(sceneMeta.processingMode || "", sceneMeta);
        currentOverlays = data.overlays;
        const sceneWallHeight = Number(currentSceneData.meta.wallHeight);
        if (Number.isFinite(sceneWallHeight) && sceneWallHeight >= Number(inputWallHeight.min) && sceneWallHeight <= Number(inputWallHeight.max)) {
            inputWallHeight.value = String(sceneWallHeight);
            labelWallHeight.textContent = `${sceneWallHeight.toFixed(1)} m`;
        }
        const sceneWallThickness = Number(currentSceneData.meta.wallThickness);
        if (Number.isFinite(sceneWallThickness) && sceneWallThickness >= Number(inputWallThickness.min) && sceneWallThickness <= Number(inputWallThickness.max)) {
            inputWallThickness.value = String(sceneWallThickness);
            labelWallThickness.textContent = `${sceneWallThickness.toFixed(2)} m`;
        }
        const levels = currentSceneData.meta.levels || [];
        levelFilter.replaceChildren(new Option("All Stories", "all"));
        levels.forEach(level => levelFilter.add(new Option(level.name || `Level ${Number(level.level) + 1}`, String(level.level))));
        levelFilter.classList.toggle("hidden", levels.length < 2);
        levelFilter.value = "all";
        viewer.setVisibleLevel(null);
        populateRoomControls(currentSceneData);
        if (currentSceneData.meta && Number.isFinite(Number(currentSceneData.meta.metersPerPixel))) {
            inputMpp.value = String(currentSceneData.meta.metersPerPixel);
            labelMpp.textContent = `${Number(currentSceneData.meta.metersPerPixel).toFixed(3)} m/px`;
            overlayScale.textContent = `Scale: ${Number(currentSceneData.meta.metersPerPixel).toFixed(3)} m/px`;
        }

        if (data.imageUrl) {
            imagePreview.src = data.imageUrl;
            imagePreviewContainer.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");
            if (floorPlanImages.length) {
                loadedImageElement = floorPlanImages[0];
                render2DSegmentationCanvas();
            } else {
                const img = new Image();
                img.onload = () => {
                    loadedImageElement = img;
                    render2DSegmentationCanvas();
                };
                img.src = data.imageUrl;
            }
        } else if (loadedImageElement) {
            render2DSegmentationCanvas();
        }

        // Saved review samples remain inspectable in 3D, with their review warning visible.
        // Newly processed implausible uploads stay in 2D review until corrected.
        if (needsReview && !isSavedSample) {
            viewer.clear();
            viewer.hideLoadingState();
        } else {
            viewer.loadScene(data.scene);
            if (data.imageUrl && data.scene && data.scene.meta) {
                viewer.setBlueprintImage(data.imageUrl, data.scene.meta.imageSize, data.scene.meta.metersPerPixel);
            }
        }

        // 2. Populate scene.json viewer
        jsonOutput.textContent = JSON.stringify(data.scene, null, 2);

        // 3. Switch to 3D tab
        document.querySelector(`[data-tab="${needsReview && !isSavedSample ? "2d" : "3d"}"]`)?.click();
        updateAreaSummary();
        if (needsReview) {
            showMessage(`Needs review before 3D: ${(sceneMeta.reviewIssues || []).join(" ") || "Check the scale and 2D detections."}`, "warning");
        }
        if (typeof switchSidebarTab === "function") {
            switchSidebarTab("review");
        }
    }

    // -------------------------------------------------------------
    // 2D AI Segmentation Canvas Renderer
    // -------------------------------------------------------------
    function render2DSegmentationCanvas() {
        if (!loadedImageElement || !segmentationCanvas || !segCtx) return;

        const img = loadedImageElement;
        segmentationCanvas.width = img.naturalWidth || 800;
        segmentationCanvas.height = img.naturalHeight || 600;

        // 1. Draw original floor plan base image
        segCtx.clearRect(0, 0, segmentationCanvas.width, segmentationCanvas.height);
        segCtx.drawImage(img, 0, 0, segmentationCanvas.width, segmentationCanvas.height);

        // 2. If overlays exist, draw color-coded masks
        if (!currentSceneData) return;

        const selectedLevel = levelFilter.value === "all" ? null : Number(levelFilter.value);
        const overlayLevel = selectedLevel ?? (floorPlanImages.length > 1 ? 0 : null);
        const drawScale = scaleForLevel(selectedLevel ?? overlayLevel ?? 0);
        if (drawScale && drawScale > 0 && overlayScale) overlayScale.textContent = `Scale: ${drawScale.toFixed(4)} m/px`;
        const belongsToSelectedLevel = item => selectedLevel === null
            ? (overlayLevel === null || (Number(item.level ?? item.floorIndex) || 0) === overlayLevel)
            : (Number(item.level ?? item.floorIndex) || 0) === selectedLevel;
        const sourcePoint = (item, point) => scenePointToSourcePixels(item, point);

        // Draw Room Polygons
        (currentSceneData.rooms || []).filter(belongsToSelectedLevel).forEach(room => {
            const poly = room.polygon || [];
            if (poly.length < 3) return;

            segCtx.beginPath();
            const firstPoint = sourcePoint(room, poly[0]);
            segCtx.moveTo(firstPoint[0], firstPoint[1]);
            for (let i = 1; i < poly.length; i++) {
                const point = sourcePoint(room, poly[i]);
                segCtx.lineTo(point[0], point[1]);
            }
            segCtx.closePath();
            (room.holes || []).forEach(hole => {
                if (!Array.isArray(hole) || hole.length < 3) return;
                const firstHolePoint = sourcePoint(room, hole[0]);
                segCtx.moveTo(firstHolePoint[0], firstHolePoint[1]);
                hole.slice(1).forEach(point => {
                    const source = sourcePoint(room, point);
                    segCtx.lineTo(source[0], source[1]);
                });
                segCtx.closePath();
            });

            // Fill color matching room type
            segCtx.fillStyle = getRoomTypeCanvasColor(room.type);
            segCtx.fill("evenodd");
            segCtx.strokeStyle = "#121212";
            segCtx.lineWidth = 3;
            segCtx.stroke();

            // Draw a square paper label with an ink outline.
            const [centroidX, centroidY] = sourcePoint(room, room.centroid || roomCentroid(room));
            const cx = centroidX;
            const cy = centroidY;

            segCtx.fillStyle = "#F0F0F0";
            segCtx.fillRect(cx - 50, cy - 14, 100, 24);
            segCtx.strokeStyle = "#121212";
            segCtx.lineWidth = 2;
            segCtx.strokeRect(cx - 50, cy - 14, 100, 24);
            segCtx.fillStyle = "#121212";
            segCtx.font = "700 12px 'Outfit', sans-serif";
            segCtx.textAlign = "center";
            segCtx.fillText(room.label || room.id, cx, cy + 2);
        });

        if (polygonEditActive) {
            const room = (currentSceneData.rooms || []).find(item => item.id === selectedRoomId && belongsToSelectedLevel(item));
            if (room) {
                const radius = Math.max(6, Math.min(11, segmentationCanvas.width / 100));
                room.polygon.forEach((point, index) => {
                    const [sourceX, sourceY] = sourcePoint(room, point);
                    const x = sourceX;
                    const y = sourceY;
                    segCtx.beginPath();
                    segCtx.arc(x, y, radius, 0, Math.PI * 2);
                    segCtx.fillStyle = index === polygonEditDragIndex ? "#D02020" : "#00A6C7";
                    segCtx.fill();
                    segCtx.lineWidth = Math.max(2, radius * 0.25);
                    segCtx.strokeStyle = "#FFFFFF";
                    segCtx.stroke();
                    segCtx.fillStyle = "#121212";
                    segCtx.font = `bold ${Math.max(10, radius * 1.3)}px sans-serif`;
                    segCtx.textAlign = "center";
                    segCtx.textBaseline = "middle";
                    segCtx.fillText(String(index + 1), x, y);
                });
            }
        }

        // Draw Doors
        (currentSceneData.doors || []).filter(belongsToSelectedLevel).forEach(door => {
            const [sourceX, sourceY] = sourcePoint(door, door.center || [0, 0]);
            const cx = sourceX;
            const cy = sourceY;
            const w = (door.width || 0.9) / scaleForLevel(entityFloorIndex(door));

            segCtx.strokeStyle = selectedOpening?.kind === "door" && selectedOpening.id === door.id ? "#f0a020" : "#D02020";
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.arc(cx, cy, w / 2, 0, Math.PI * 2);
            segCtx.stroke();
        });

        // Draw Windows
        (currentSceneData.windows || []).filter(belongsToSelectedLevel).forEach(win => {
            const [sourceX, sourceY] = sourcePoint(win, win.center || [0, 0]);
            const cx = sourceX;
            const cy = sourceY;
            const w = (win.width || 1.2) / scaleForLevel(entityFloorIndex(win));

            segCtx.strokeStyle = selectedOpening?.kind === "window" && selectedOpening.id === win.id ? "#f0a020" : "#1040C0";
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.moveTo(cx - w / 2, cy);
            segCtx.lineTo(cx + w / 2, cy);
            segCtx.stroke();
        });

        // Rejected detector candidates stay visible as red crosses so they can
        // be compared to the source plan; the review checklist explains why.
        (currentSceneData.meta?.openingDiagnostics || [])
            .filter(item => item && item.accepted === false && item.pixelCenter
                && (selectedLevel === null || entityFloorIndex(item) === selectedLevel))
            .slice(0, 80)
            .forEach(item => {
                const x = Number(item.pixelCenter[0]);
                const y = Number(item.pixelCenter[1]);
                if (!Number.isFinite(x) || !Number.isFinite(y)) return;
                const size = Math.max(5, Math.min(12, segmentationCanvas.width / 100));
                segCtx.strokeStyle = "#D02020";
                segCtx.lineWidth = Math.max(2, size / 4);
                segCtx.beginPath();
                segCtx.moveTo(x - size, y - size);
                segCtx.lineTo(x + size, y + size);
                segCtx.moveTo(x + size, y - size);
                segCtx.lineTo(x - size, y + size);
                segCtx.stroke();
            });

        scaleCalibrationPoints.forEach((point, index) => {
            segCtx.fillStyle = "#D02020";
            segCtx.strokeStyle = "#FFFFFF";
            segCtx.lineWidth = Math.max(2, segmentationCanvas.width / 500);
            segCtx.beginPath();
            segCtx.arc(point[0], point[1], Math.max(6, segmentationCanvas.width / 100), 0, Math.PI * 2);
            segCtx.fill();
            segCtx.stroke();
            segCtx.fillStyle = "#FFFFFF";
            segCtx.font = `bold ${Math.max(12, segmentationCanvas.width / 40)}px sans-serif`;
            segCtx.textAlign = "center";
            segCtx.textBaseline = "middle";
            segCtx.fillText(String(index + 1), point[0], point[1]);
        });
    }

    function getRoomTypeCanvasColor(type) {
        const colors = {
            classroom: "rgba(16, 64, 192, 0.28)",
            lab:       "rgba(208, 32, 32, 0.28)",
            corridor:  "rgba(224, 224, 224, 0.55)",
            restroom:  "rgba(16, 64, 192, 0.2)",
            stairs:    "rgba(240, 192, 32, 0.38)",
            elevator:  "rgba(208, 32, 32, 0.2)",
            entrance:  "rgba(240, 192, 32, 0.38)",
            room:      "rgba(224, 224, 224, 0.35)",
            other:     "rgba(224, 224, 224, 0.35)"
        };
        return colors[type] || colors.other;
    }

    // -------------------------------------------------------------
    // Room Inspector Card Callback
    // -------------------------------------------------------------
    window.onFloorPlanRoomSelected = (room) => {
        if (!room) return;
        selectedRoomId = room.id;
        if (inspectorEmpty) inspectorEmpty.classList.add("hidden");
        if (inspectorCard) inspectorCard.classList.remove("hidden");

        if (inspectorTitle) inspectorTitle.textContent = room.label || `Room ${room.id}`;
        if (inspectorType) inspectorType.textContent = (room.type || "room").toUpperCase();
        
        const confidence = Number(room.confidence);
        if (inspectorConf) {
            inspectorConf.textContent = Number.isFinite(confidence) && confidence > 0
                ? `${Math.round(confidence * 100)}%`
                : "—";
        }

        // Calculate approximate area in sq meters
        const poly = room.polygon || [];
        const area = roomArea(room);
        const sqft = area * 10.7639;
        inspectorArea.textContent = `${area.toFixed(1)} m² (${sqft.toFixed(0)} sq ft)`;
        inspectorPoints.textContent = `${poly.length} Vertices`;

        // Connected doors check
        if (inspectorDoors) {
            if (currentSceneData && currentSceneData.doors) {
                const connected = currentSceneData.doors.filter(d => (d.connects || []).includes(room.id));
                if (connected.length > 0) {
                    inspectorDoors.textContent = connected.map(d => d.id).join(", ");
                } else {
                    inspectorDoors.textContent = "None";
                }
            } else {
                inspectorDoors.textContent = "None";
            }
        }

        if (editRoomName) editRoomName.value = room.label || "";
        if (editRoomType) {
            const typeOption = Array.from(editRoomType.options).find(option => option.value === (room.type || "room"));
            if (!typeOption) editRoomType.add(new Option(room.type || "room", room.type || "room"));
            editRoomType.value = room.type || "room";
        }
        [editRoomName, editRoomType, btnSaveRoomEdit, btnDeleteRoom, btnEditBoundary].forEach(control => { if (control) control.disabled = false; });
    };

    if (btnSaveRoomEdit) btnSaveRoomEdit.addEventListener("click", () => {
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        const name = editRoomName.value.trim();
        if (!room || !name) {
            showMessage("Select a room and enter a non-empty room name.", "error");
            return;
        }
        room.label = name.slice(0, 100);
        room.type = editRoomType.value || "room";
        refreshEditedScene();
        showMessage("Room edit saved to the scene. Export scene.json or GLB to keep it.");
    });

    if (btnDeleteRoom) btnDeleteRoom.addEventListener("click", () => {
        if (!currentSceneData || !selectedRoomId) return;
        const deletedId = selectedRoomId;
        const candidate = JSON.parse(JSON.stringify(currentSceneData));
        candidate.rooms = candidate.rooms.filter(room => room.id !== deletedId);
        candidate.doors = (candidate.doors || []).map(door => ({
            ...door,
            connects: (door.connects || []).filter(roomId => roomId !== deletedId),
        })).filter(door => (door.connects || []).length > 0);
        rebuildEditedGeometry(candidate, "Room removed and wall geometry rebuilt locally.");
    });

    // -------------------------------------------------------------
    // Copy & Download scene.json
    // -------------------------------------------------------------
    if (btnCopyJson) btnCopyJson.addEventListener("click", () => {
        if (!currentSceneData) return;
        navigator.clipboard.writeText(JSON.stringify(currentSceneData, null, 2))
            .then(() => {
                const originalText = btnCopyJson.textContent;
                btnCopyJson.textContent = "Copied!";
                setTimeout(() => { btnCopyJson.textContent = originalText; }, 2000);
            })
            .catch(err => alert("Copy failed: " + err));
    });

    if (btnDownloadJson) btnDownloadJson.addEventListener("click", () => {
        if (!currentSceneData) return;
        const jsonStr = JSON.stringify(currentSceneData, null, 2);
        const blob = new Blob([jsonStr], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "scene.json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    // -------------------------------------------------------------
    // Download 3D Model as binary .GLB
    // -------------------------------------------------------------
    function triggerGlbExport() {
        if (!currentSceneData) {
            alert("Please load a floor plan or run the AI pipeline first.");
            return;
        }
        viewer.exportGLB("floorplan3d_model.glb");
    }

    if (btnExportGlb) {
        btnExportGlb.addEventListener("click", triggerGlbExport);
    }
    if (btnDownloadGlbTab) {
        btnDownloadGlbTab.addEventListener("click", triggerGlbExport);
    }

    // -------------------------------------------------------------
    // 1. Dynamic Sunlight & Night-Mode Light Simulation
    // -------------------------------------------------------------
    const btnToggleSunlight = document.getElementById("btn-toggle-sunlight");
    const sunlightPanel = document.getElementById("sunlight-panel");
    const btnCloseSunlight = document.getElementById("btn-close-sunlight");
    const inputSunTime = document.getElementById("input-sun-time");
    const labelSunTime = document.getElementById("label-sun-time");
    const sunIcon = document.getElementById("sun-icon");
    const btnPresetDay = document.getElementById("btn-preset-day");
    const btnPresetNight = document.getElementById("btn-preset-night");

    function formatTimeLabel(hour) {
        const h = Math.floor(hour);
        const m = Math.round((hour - h) * 60);
        const mStr = m === 0 ? "00" : (m < 10 ? "0" + m : m);
        const ampm = h >= 12 ? "PM" : "AM";
        const h12 = h % 12 === 0 ? 12 : h % 12;
        return `${h12}:${mStr} ${ampm}`;
    }

    function updateSunlightUI(hour) {
        if (labelSunTime) labelSunTime.textContent = formatTimeLabel(hour);
        if (inputSunTime) inputSunTime.value = hour;
        if (sunIcon) {
            sunIcon.textContent = "";
        }
        viewer.setTimeOfDay(hour);
    }

    if (btnToggleSunlight && sunlightPanel) {
        btnToggleSunlight.addEventListener("click", () => {
            sunlightPanel.classList.toggle("hidden");
            if (blueprintPanel) blueprintPanel.classList.add("hidden");
        });
    }
    if (btnCloseSunlight && sunlightPanel) {
        btnCloseSunlight.addEventListener("click", () => sunlightPanel.classList.add("hidden"));
    }
    if (inputSunTime) {
        inputSunTime.addEventListener("input", e => updateSunlightUI(parseFloat(e.target.value)));
    }
    if (btnPresetDay) {
        btnPresetDay.addEventListener("click", () => updateSunlightUI(13.0));
    }
    if (btnPresetNight) {
        btnPresetNight.addEventListener("click", () => updateSunlightUI(21.0));
    }

    // -------------------------------------------------------------
    // 2. 2D Blueprint Underlay Projection
    // -------------------------------------------------------------
    const btnToggleBlueprint = document.getElementById("btn-toggle-blueprint");
    const blueprintPanel = document.getElementById("blueprint-panel");
    const btnCloseBlueprint = document.getElementById("btn-close-blueprint");
    const inputBlueprintOpacity = document.getElementById("input-blueprint-opacity");
    const labelBlueprintOpacity = document.getElementById("label-blueprint-opacity");
    const btnBlueprintZero = document.getElementById("btn-blueprint-zero");
    const btnBlueprintHalf = document.getElementById("btn-blueprint-half");
    const btnBlueprintFull = document.getElementById("btn-blueprint-full");

    function updateBlueprintOpacityUI(val) {
        const opacity = val / 100.0;
        if (inputBlueprintOpacity) inputBlueprintOpacity.value = val;
        if (labelBlueprintOpacity) {
            labelBlueprintOpacity.textContent = val === 0 ? "0% (Off)" : `${val}%`;
        }
        viewer.setBlueprintOpacity(opacity);
    }

    if (btnToggleBlueprint && blueprintPanel) {
        btnToggleBlueprint.addEventListener("click", () => {
            blueprintPanel.classList.toggle("hidden");
            if (sunlightPanel) sunlightPanel.classList.add("hidden");
        });
    }
    if (btnCloseBlueprint && blueprintPanel) {
        btnCloseBlueprint.addEventListener("click", () => blueprintPanel.classList.add("hidden"));
    }
    if (inputBlueprintOpacity) {
        inputBlueprintOpacity.addEventListener("input", e => updateBlueprintOpacityUI(parseInt(e.target.value, 10)));
    }
    if (btnBlueprintZero) {
        btnBlueprintZero.addEventListener("click", () => updateBlueprintOpacityUI(0));
    }
    if (btnBlueprintHalf) {
        btnBlueprintHalf.addEventListener("click", () => updateBlueprintOpacityUI(50));
    }
    if (btnBlueprintFull) {
        btnBlueprintFull.addEventListener("click", () => updateBlueprintOpacityUI(100));
    }

    // -------------------------------------------------------------
    // 3. Emergency Evacuation Life-Safety Simulator
    // -------------------------------------------------------------
    const btnToggleEvacuation = document.getElementById("btn-toggle-evacuation");
    const btnSidebarEvac = document.getElementById("btn-sidebar-evac");
    const evacuationCard = document.getElementById("evacuation-card");
    const btnCloseEvacuation = document.getElementById("btn-close-evacuation");
    const evacExitCount = document.getElementById("evac-exit-count");
    const evacRoomCount = document.getElementById("evac-room-count");
    const evacMaxDist = document.getElementById("evac-max-dist");
    const evacAvgDist = document.getElementById("evac-avg-dist");
    const evacCompliance = document.getElementById("evac-compliance");

    function runEvacuationSimulation() {
        if (!currentSceneData) {
            showMessage("Load a floor plan or demo scene first to simulate evacuation routes.", "warning");
            return;
        }
        const tab3d = document.querySelector('[data-tab="3d"]');
        if (tab3d) tab3d.click();

        const report = viewer.simulateEvacuation();
        if (report && report.success) {
            if (evacExitCount) evacExitCount.textContent = `${report.exitCount} candidate exit(s) · ${report.exitSource}`;
            if (evacRoomCount) evacRoomCount.textContent = `${report.roomCount} of ${report.totalRooms} Rooms Connected`;
            if (evacMaxDist) evacMaxDist.textContent = `${report.maxDistance} m`;
            if (evacAvgDist) evacAvgDist.textContent = `${report.avgDistance} m`;
            if (evacCompliance) evacCompliance.textContent = "Not assessed";
            if (evacuationCard) evacuationCard.classList.remove("hidden");
            showMessage("Egress connectivity preview active. It shows graph routes and estimated lengths only; it does not assess evacuation safety or code compliance.", "info");
        } else {
            showMessage("Could not compute evacuation paths: check door connectivity in the scene.", "warning");
        }
    }

    function stopEvacuationSimulation() {
        viewer.clearEvacuation();
        if (evacuationCard) evacuationCard.classList.add("hidden");
        clearMessage();
    }

    if (btnToggleEvacuation) {
        btnToggleEvacuation.addEventListener("click", () => {
            if (viewer.evacuationActive) {
                stopEvacuationSimulation();
            } else {
                runEvacuationSimulation();
            }
        });
    }
    if (btnSidebarEvac) {
        btnSidebarEvac.addEventListener("click", runEvacuationSimulation);
    }
    if (btnCloseEvacuation) {
        btnCloseEvacuation.addEventListener("click", stopEvacuationSimulation);
    }

    // Wire up sidebar tabs, samples, collapse toggle, walkthrough, inspector
    sidebarTabBtns.forEach((btn, index) => {
        btn.addEventListener("click", () => {
            switchSidebarTab(btn.dataset.tab);
        });
        btn.addEventListener("keydown", (e) => {
            let targetIdx = index;
            if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                targetIdx = (index + 1) % sidebarTabBtns.length;
            } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                targetIdx = (index - 1 + sidebarTabBtns.length) % sidebarTabBtns.length;
            } else if (e.key === "Home") {
                targetIdx = 0;
            } else if (e.key === "End") {
                targetIdx = sidebarTabBtns.length - 1;
            } else {
                return;
            }
            e.preventDefault();
            const targetBtn = sidebarTabBtns[targetIdx];
            if (targetBtn) {
                targetBtn.focus();
                switchSidebarTab(targetBtn.dataset.tab);
            }
        });
    });

    if (sidebarSamplesSelect) {
        sidebarSamplesSelect.addEventListener("change", (e) => {
            const val = e.target.value;
            if (val === "demo" && btnLoadDemo) {
                btnLoadDemo.click();
            } else if (val === "two-story" && btnLoadTwoStoryDemo) {
                btnLoadTwoStoryDemo.click();
            } else if (val === "evac" && btnSidebarEvac) {
                btnSidebarEvac.click();
            } else if (["two-plans", "three-story", "four-story"].includes(val)) {
                loadPreparedPlan(val);
            }
        });
    }

    async function loadPreparedPlan(sampleId) {
        try {
            viewer.showLoadingState();
            const response = await fetch(`/api/sample/${encodeURIComponent(sampleId)}`);
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || "Could not load this saved sample.");
            handleProcessSuccess(data);
            const usedMuseLabels = String(data.scene.meta?.labeling || "").toLowerCase() === "muse";
            const provenance = usedMuseLabels
                ? "Saved sample loaded with room labels previously generated by Meta Muse Spark. Loading it makes no new model call."
                : "Saved sample loaded with its stored geometry and local labels. Loading it makes no model call.";
            showMessage(data.scene.meta.needsReview
                ? `${provenance} Review flagged geometry before relying on the 3D view.`
                : provenance, data.scene.meta.needsReview ? "warning" : "info");
        } catch (error) {
            viewer.hideLoadingState();
            showMessage(error.message || "Could not load this saved sample.", "error");
        } finally {
            if (sidebarSamplesSelect) sidebarSamplesSelect.value = "";
        }
    }

    if (btnJudgeHelp && popoverJudgeWalkthrough) {
        btnJudgeHelp.addEventListener("click", (e) => {
            e.stopPropagation();
            const isHidden = popoverJudgeWalkthrough.classList.toggle("hidden");
            btnJudgeHelp.setAttribute("aria-expanded", !isHidden);
        });
        if (btnCloseWalkthroughPopover) {
            btnCloseWalkthroughPopover.addEventListener("click", (e) => {
                e.stopPropagation();
                popoverJudgeWalkthrough.classList.add("hidden");
                btnJudgeHelp.setAttribute("aria-expanded", "false");
            });
        }
        document.addEventListener("click", (e) => {
            if (!popoverJudgeWalkthrough.contains(e.target) && e.target !== btnJudgeHelp) {
                popoverJudgeWalkthrough.classList.add("hidden");
                btnJudgeHelp.setAttribute("aria-expanded", "false");
            }
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && !popoverJudgeWalkthrough.classList.contains("hidden")) {
                popoverJudgeWalkthrough.classList.add("hidden");
                btnJudgeHelp.setAttribute("aria-expanded", "false");
            }
        });
    }

    if (btnToggleSidebar && sidebarEl) {
        btnToggleSidebar.addEventListener("click", () => {
            const isCollapsed = sidebarEl.classList.toggle("is-collapsed");
            const toggleIcon = document.getElementById("sidebar-toggle-icon");
            if (toggleIcon) {
                toggleIcon.setAttribute("href", isCollapsed ? "#icon-chevron-right" : "#icon-chevron-left");
            } else {
                btnToggleSidebar.textContent = isCollapsed ? ">" : "<";
            }
            btnToggleSidebar.setAttribute("aria-expanded", !isCollapsed);
            btnToggleSidebar.setAttribute("aria-label", isCollapsed ? "Expand sidebar" : "Collapse sidebar");
            window.dispatchEvent(new Event("resize"));
        });
    }

    if (sidebarSheetHandle && sidebarEl) {
        sidebarSheetHandle.addEventListener("click", () => {
            sidebarEl.classList.toggle("sheet-expanded");
        });
    }

    if (btnCloseInspector && inspectorCard) {
        btnCloseInspector.addEventListener("click", () => {
            inspectorCard.classList.add("hidden");
            if (inspectorEmpty) inspectorEmpty.classList.remove("hidden");
            selectedRoomId = null;
            if (viewer && typeof viewer.clearRoomSelection === "function") {
                viewer.clearRoomSelection();
            }
            [editRoomName, editRoomType, btnSaveRoomEdit, btnDeleteRoom].forEach(control => {
                if (control) control.disabled = true;
            });
            if (btnEditBoundary) btnEditBoundary.disabled = true;
            const bControls = document.getElementById("boundary-edit-controls");
            if (bControls) bControls.classList.add("hidden");
        });
    }
});
