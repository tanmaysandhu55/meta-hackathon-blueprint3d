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
    const btnViewTop = document.getElementById("btn-view-top");
    const btnViewEye = document.getElementById("btn-view-eye");
    const btnViewReset = document.getElementById("btn-view-reset");
    const btnCutaway = document.getElementById("btn-cutaway");

    // Layer checkboxes
    const chkWalls = document.getElementById("chk-walls");
    const chkFloors = document.getElementById("chk-floors");
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
    const segCtx = segmentationCanvas.getContext("2d");
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

    function setProcessingBadge(mode) {
        if (!processingModeBadge) return;
        const messages = {
            MOCK: "MOCK MODE — PREPARED SAMPLE, NOT LIVE AI",
            DEMO: "PREPARED DEMO — NOT A LIVE AI RESULT",
            LIVE: "META SAM 3.1 RESULT",
            LOCAL: "LOCAL OPENCV SEGMENTATION — LABELING OPTIONAL",
        };
        if (!messages[mode]) {
            processingModeBadge.classList.add("hidden");
            processingModeBadge.textContent = "";
            return;
        }
        processingModeBadge.textContent = messages[mode];
        processingModeBadge.title = mode === "MOCK"
            ? "Generated from the prepared sample plan. Uploaded image pixels were not analyzed."
            : mode === "LOCAL"
                ? "OpenCV analyzes plans locally; Meta SAM 3.1 can segment uploads, and Baseten-hosted Muse Spark Open can suggest room labels."
                : mode === "LIVE"
                    ? "At least one segmentation concept was processed by Meta SAM 3.1. Check scene warnings for local fallback concepts."
                : "Prepared sample data, not a live provider result.";
        processingModeBadge.classList.remove("hidden");
    }

    if (initialProcessingMode === "MOCK") setProcessingBadge(initialProcessingMode);

    function showMessage(message, kind = "info") {
        if (!appMessage) return;
        appMessage.textContent = message;
        appMessage.classList.remove("hidden", "border-rose-500/40", "text-rose-200", "border-amber-500/40", "text-amber-100", "border-blue-500/40", "text-blue-100");
        if (kind === "error") appMessage.classList.add("border-rose-500/40", "text-rose-200");
        else if (kind === "warning") appMessage.classList.add("border-amber-500/40", "text-amber-100");
        else appMessage.classList.add("border-blue-500/40", "text-blue-100");
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
            areaSummaryTotal.textContent = "Load a plan to calculate areas.";
            areaSummaryRooms.replaceChildren();
            mapQualityReport.textContent = "Load a plan to review its detected geometry.";
            mapQualityChecks.replaceChildren();
            mapQualityWarnings.replaceChildren();
            return;
        }
        const rooms = currentSceneData.rooms || [];
        const meta = currentSceneData.meta || {};
        const totalArea = rooms.reduce((sum, room) => sum + polygonArea(room.polygon), 0);
        areaSummaryTotal.textContent = `${rooms.length} rooms · ${totalArea.toFixed(1)} m² total`;
        areaSummaryRooms.replaceChildren();
        rooms.forEach(room => {
            const row = document.createElement("li");
            row.className = "flex justify-between gap-2 border-b border-bauhaus-muted py-1";
            const name = document.createElement("span");
            name.textContent = room.label || room.id;
            const area = document.createElement("span");
            area.className = "font-mono";
            area.textContent = `${polygonArea(room.polygon).toFixed(1)} m²`;
            row.append(name, area);
            areaSummaryRooms.appendChild(row);
        });
        const validRoomCount = rooms.filter(room => (room.polygon || []).length >= 3 && polygonArea(room.polygon) > 0).length;
        const roomLevels = rooms.map(room => Number(room.floorIndex ?? room.level) || 0);
        const floorCount = Math.max(1, (meta.levels || []).length, Number(meta.levelCount) || 0, ...roomLevels.map(level => level + 1));
        const connectorCount = rooms.filter(room => ["stairs", "stair", "elevator"].includes(String(room.type || "").toLowerCase())).length;
        const walls = currentSceneData.walls || [];
        const doors = currentSceneData.doors || [];
        const windows = currentSceneData.windows || [];
        const warnings = Array.isArray(meta.warnings) ? meta.warnings : [];
        const genericLabel = label => /^room\s+\w+$/i.test(String(label || "").trim());
        const namedRoomCount = rooms.filter(room => room.confidence > 0 && !genericLabel(room.label)).length;
        const scaleMethod = String(meta.scaleMethod || "");
        const scaleNeedsReview = !scaleMethod || /fallback/i.test(scaleMethod);
        const rows = [
            { state: validRoomCount === rooms.length && rooms.length > 0 ? "ok" : "review", label: "Room outlines", detail: `${validRoomCount} of ${rooms.length} have a usable polygon.` },
            { state: walls.length ? "ok" : "review", label: "Walls", detail: `${walls.length} wall region(s) in the scene.` },
            { state: doors.length ? "ok" : "review", label: "Doors", detail: `${doors.length} detected opening(s); check the 2D overlay for alignment.` },
            { state: windows.length ? "ok" : "review", label: "Windows", detail: `${windows.length} detected opening(s); check the 2D overlay for alignment.` },
            { state: scaleNeedsReview ? "review" : "info", label: "Scale", detail: scaleNeedsReview ? "No verified calibration recorded. Compare with a known dimension." : `${scaleMethod}; confirm against a known dimension.` },
            { state: floorCount < 2 || connectorCount > 0 ? "ok" : "review", label: "Floor connection", detail: floorCount < 2 ? "Single-story scene." : `${connectorCount} stair/elevator room(s) for ${floorCount} floors.` },
            { state: namedRoomCount === rooms.length && rooms.length > 0 ? "ok" : "review", label: "Room labels", detail: `${namedRoomCount} of ${rooms.length} have non-generic labels.` },
        ];
        mapQualityChecks.replaceChildren();
        rows.forEach(item => {
            const row = document.createElement("li");
            row.className = "flex gap-1.5";
            const marker = document.createElement("span");
            marker.className = item.state === "ok" ? "font-bold text-green-700" : item.state === "review" ? "font-bold text-bauhaus-red" : "font-bold text-bauhaus-blue";
            marker.textContent = item.state === "ok" ? "✓" : item.state === "review" ? "!" : "i";
            marker.setAttribute("aria-label", item.state === "ok" ? "Checked" : item.state === "review" ? "Review" : "Information");
            const text = document.createElement("span");
            text.textContent = `${item.label}: ${item.detail}`;
            row.append(marker, text);
            mapQualityChecks.appendChild(row);
        });
        mapQualityWarnings.replaceChildren();
        const warningItems = warnings.length ? warnings : ["No pipeline warnings recorded."];
        warningItems.forEach(warning => {
            const row = document.createElement("li");
            row.textContent = warnings.length ? `• ${warning}` : warning;
            mapQualityWarnings.appendChild(row);
        });
        mapQualityReport.textContent = `${rooms.length} rooms · ${floorCount} floor(s) · ${totalArea.toFixed(1)} m² estimated area. These are review checks, not an accuracy score.`;
    }

    btnReview2D.addEventListener("click", () => {
        if (!currentSceneData) {
            showMessage("Load a demo or plan before reviewing 2D detections.", "info");
            return;
        }
        document.querySelector('[data-tab="2d"]').click();
    });

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
        window.onFloorPlanRoomSelected(room);
        btnEditBoundary.click();
    });

    function refreshEditedScene() {
        if (!currentSceneData) return;
        viewer.loadScene(currentSceneData, { animateBuild: false, resetCamera: false });
        jsonOutput.textContent = JSON.stringify(currentSceneData, null, 2);
        updateAreaSummary();
        populateRoomControls(currentSceneData);
        if (loadedImageElement) render2DSegmentationCanvas();
        inspectorCard.classList.add("hidden");
        inspectorEmpty.classList.remove("hidden");
        selectedRoomId = null;
        [editRoomName, editRoomType, btnSaveRoomEdit, btnDeleteRoom].forEach(control => { control.disabled = true; });
        btnEditBoundary.disabled = true;
    }

    function refreshBoundaryScene() {
        if (!currentSceneData) return;
        currentSceneData.rooms.forEach(room => {
            room.area_m2 = polygonArea(room.polygon || []);
            room.centroid = roomCentroid(room);
        });
        viewer.loadScene(currentSceneData, { animateBuild: false, resetCamera: false });
        jsonOutput.textContent = JSON.stringify(currentSceneData, null, 2);
        updateAreaSummary();
        populateRoomControls(currentSceneData);
        if (loadedImageElement) render2DSegmentationCanvas();
        const room = currentSceneData.rooms.find(item => item.id === selectedRoomId);
        if (room) {
            window.onFloorPlanRoomSelected(room);
            viewer.previewRoomBoundary(room);
        }
    }

    function showRoomRoute(scene, startId, endId) {
        const rooms = new Map((scene.rooms || []).map(room => [room.id, room]));
        if (!rooms.has(startId) || !rooms.has(endId) || startId === endId) {
            routeStatus.textContent = "Choose two different rooms.";
            viewer.clearRoute();
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
        routeStatus.textContent = `Route shown through ${doorCount} door${doorCount === 1 ? "" : "s"} and ${floorChanges} floor change${floorChanges === 1 ? "" : "s"}.`;
    }

    btnFocusRoom.addEventListener("click", () => {
        const room = (currentSceneData?.rooms || []).find(item => item.id === roomSearch.value);
        if (!room) {
            routeStatus.textContent = "Load a scene and choose a room first.";
            return;
        }
        viewer.focusRoom(room);
    });

    btnShowRoute.addEventListener("click", () => {
        if (!currentSceneData) {
            routeStatus.textContent = "Load a scene before creating a route.";
            return;
        }
        showRoomRoute(currentSceneData, routeFrom.value, routeTo.value);
    });

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

    btnTranscribeMap.addEventListener("click", async () => {
        if (!mapAudioInput.files.length) {
            mapTranscriptionStatus.textContent = "Choose a supported mono PCM WAV recording first.";
            return;
        }
        btnTranscribeMap.disabled = true;
        mapTranscriptionStatus.textContent = "Transcribing…";
        try {
            const formData = new FormData();
            formData.append("audio", mapAudioInput.files[0]);
            const response = await fetch("/api/transcribe", { method: "POST", body: formData });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || "Transcription failed.");
            mapAssistantQuestion.value = result.transcript;
            mapTranscriptionStatus.textContent = "Transcript added to the question box. Review it, then select Ask map assistant.";
        } catch (error) {
            mapTranscriptionStatus.textContent = error.message || "Transcription is unavailable.";
        } finally {
            btnTranscribeMap.disabled = false;
        }
    });

    // -------------------------------------------------------------
    // Slider Events
    // -------------------------------------------------------------
    inputMpp.addEventListener("input", (e) => {
        labelMpp.textContent = `${parseFloat(e.target.value).toFixed(3)} m/px`;
    });

    chkAutoScale.addEventListener("change", () => {
        inputMpp.disabled = chkAutoScale.checked;
        inputMpp.classList.toggle("opacity-40", chkAutoScale.checked);
    });
    inputMpp.disabled = chkAutoScale.checked;
    inputMpp.classList.toggle("opacity-40", chkAutoScale.checked);

    inputWallHeight.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value).toFixed(1);
        labelWallHeight.textContent = `${val} m`;
        viewer.setWallHeight(val);
    });

    inputWallThickness.addEventListener("input", (e) => {
        const value = parseFloat(e.target.value);
        labelWallThickness.textContent = `${value.toFixed(2)} m`;
    });
    inputWallThickness.addEventListener("change", e => viewer.setWallThickness(parseFloat(e.target.value)));

    // -------------------------------------------------------------
    // Drag & Drop / File Selection
    // -------------------------------------------------------------
    dropZone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length) handleFileSelection(Array.from(e.target.files));
    });

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

    btnRemoveImage.addEventListener("click", (e) => {
        e.stopPropagation();
        selectedFile = null;
        selectedFiles = [];
        fileInput.value = "";
        imagePreviewContainer.classList.add("hidden");
        dropZonePrompt.classList.remove("hidden");
        btnGenerate.disabled = true;
        btnProcessBuilding.classList.add("hidden");
        buildingUploadStatus.classList.add("hidden");
        clearMessage();
    });

    function handleFileSelection(files) {
        const valid = files.filter(file => ["image/png", "image/jpeg", "image/webp"].includes(file.type.toLowerCase()) && file.size <= 10 * 1024 * 1024);
        if (!valid.length) {
            showMessage("Choose PNG, JPG, or WebP floor plans, each 10 MB or smaller.", "error");
            return;
        }
        clearMessage();
        selectedFiles = valid.slice(0, 8);
        selectedFile = selectedFiles[0];
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
            dropZonePrompt.classList.add("hidden");
            btnGenerate.disabled = !processingReady || !selectedFile;

            // Pre-load image for 2D canvas
            const img = new Image();
            img.onload = () => {
                loadedImageElement = img;
                if (currentSceneData) render2DSegmentationCanvas();
            };
            img.src = event.target.result;
        };
        reader.readAsDataURL(selectedFile);
    }

    // -------------------------------------------------------------
    // Camera Presets & Layer Toggles
    // -------------------------------------------------------------
    btnViewIso.addEventListener("click", () => viewer.setPerspectiveView());
    btnViewTop.addEventListener("click", () => viewer.setTopDownView());
    btnViewEye.addEventListener("click", () => {
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
    btnViewReset.addEventListener("click", () => viewer.resetCameraView());
    levelFilter.addEventListener("change", () => {
        viewer.setVisibleLevel(levelFilter.value === "all" ? null : levelFilter.value);
        if (floorPlanImages.length > 1) {
            const imageIndex = levelFilter.value === "all" ? 0 : Number(levelFilter.value);
            loadedImageElement = floorPlanImages[imageIndex] || floorPlanImages[0];
        }
        if (loadedImageElement) render2DSegmentationCanvas();
    });

    btnCutaway.addEventListener("click", () => {
        isCutawayActive = !isCutawayActive;
        if (isCutawayActive) {
            btnCutaway.classList.add("bg-amber-600", "text-white");
            btnCutaway.classList.remove("bg-slate-800", "text-slate-300");
            viewer.setWallHeight(1.1, { syncFloors: false }); // Cutaway height only; preserve story spacing.
            labelWallHeight.textContent = "1.1 m (Cutaway)";
        } else {
            btnCutaway.classList.remove("bg-amber-600", "text-white");
            btnCutaway.classList.add("bg-slate-800", "text-slate-300");
            const originalHeight = parseFloat(inputWallHeight.value) || 3.0;
            viewer.setWallHeight(originalHeight, { syncFloors: false });
            labelWallHeight.textContent = `${originalHeight.toFixed(1)} m`;
        }
    });

    chkWalls.addEventListener("change", (e) => viewer.toggleLayer("walls", e.target.checked));
    chkFloors.addEventListener("change", (e) => viewer.toggleLayer("rooms", e.target.checked));
    chkLabels.addEventListener("change", (e) => viewer.toggleLayer("labels", e.target.checked));
    chkOpenings.addEventListener("change", (e) => {
        viewer.toggleLayer("doors", e.target.checked);
        viewer.toggleLayer("windows", e.target.checked);
    });
    chkGrid.addEventListener("change", (e) => viewer.toggleLayer("grid", e.target.checked));
    chkFurniture.addEventListener("change", (e) => viewer.toggleLayer("furniture", e.target.checked));

    btnWalkthrough.addEventListener("click", () => {
        const enabled = viewer.toggleWalkthroughMode();
        btnWalkthrough.setAttribute("aria-pressed", String(enabled));
        btnWalkthrough.textContent = enabled ? "Exit Walkthrough" : "Walkthrough";
    });
    viewer.onWalkthroughChange = enabled => {
        btnWalkthrough.setAttribute("aria-pressed", String(enabled));
        btnWalkthrough.textContent = enabled ? "Exit Walkthrough" : "Walkthrough";
    };
    viewer.onWalkthroughStoryViewChange = value => { levelFilter.value = value; };
    btnMeasure.addEventListener("click", () => {
        const enabled = viewer.toggleMeasurementMode();
        btnMeasure.setAttribute("aria-pressed", String(enabled));
        btnMeasure.textContent = enabled ? "Stop Measure" : "Measure";
        measurementPanel.classList.toggle("hidden", !enabled);
        measurementStatus.textContent = enabled ? "Click a first point in the 3D view." : "Measurement stopped.";
    });
    btnClearMeasurement.addEventListener("click", () => {
        viewer.clearMeasurement();
        measurementStatus.textContent = "Click a first point to measure.";
    });
    viewer.onMeasurementUpdate = message => { measurementStatus.textContent = message; };
    viewer.onMeasurementModeChange = enabled => {
        btnMeasure.setAttribute("aria-pressed", String(enabled));
        btnMeasure.textContent = enabled ? "Stop Measure" : "Measure";
        measurementPanel.classList.toggle("hidden", !enabled);
    };

    btnCalibrateScale.addEventListener("click", () => {
        if (!currentSceneData || !loadedImageElement) {
            scaleCalibrationStatus.textContent = "Load a floor plan before calibrating scale.";
            return;
        }
        scaleCalibrationActive = true;
        scaleCalibrationPoints = [];
        btnCalibrateScale.setAttribute("aria-pressed", "true");
        btnCalibrateScale.classList.add("calibration-active");
        btnApplyScale.disabled = true;
        scaleCalibrationStatus.textContent = "Click the first point, then the second point on the plan.";
        segmentationCanvas.classList.add("calibration-crosshair");
    });

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

    btnEditBoundary.addEventListener("click", () => {
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        if (!room || !loadedImageElement || (room.polygon || []).length < 3) {
            boundaryEditStatus.textContent = "Select a room with a valid outline and its plan image first.";
            return;
        }
        polygonEditActive = true;
        segmentationCanvas.classList.add("polygon-edit-active");
        polygonEditUndoStack = [];
        polygonEditDragIndex = null;
        boundaryEditControls.classList.remove("hidden");
        boundaryEditStatus.textContent = "Open 2D Segmentation, then drag a cyan vertex to adjust the outline.";
        viewer.previewRoomBoundary(room);
        document.querySelector('[data-tab="2d"]').click();
        render2DSegmentationCanvas();
    });

    btnBoundaryUndo.addEventListener("click", () => {
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        const previous = polygonEditUndoStack.pop();
        if (!room || !previous) return;
        room.polygon = previous;
        btnBoundaryUndo.disabled = polygonEditUndoStack.length === 0;
        boundaryEditStatus.textContent = "Previous outline restored.";
        refreshBoundaryScene();
    });

    btnBoundaryDone.addEventListener("click", () => {
        polygonEditActive = false;
        segmentationCanvas.classList.remove("polygon-edit-active");
        polygonEditDragIndex = null;
        boundaryEditControls.classList.add("hidden");
        viewer.clearRoomBoundaryPreview();
        boundaryEditStatus.textContent = "Outline saved and shown on the 3D floor. The cyan edge marks the edit; detected wall solids are a separate geometry layer. Export scene.json or GLB to keep it.";
        render2DSegmentationCanvas();
    });

    segmentationCanvas.addEventListener("pointerdown", event => {
        if (!polygonEditActive || scaleCalibrationActive || !selectedRoomId) return;
        const room = (currentSceneData?.rooms || []).find(item => item.id === selectedRoomId);
        if (!room || (room.polygon || []).length < 3) return;
        const rect = segmentationCanvas.getBoundingClientRect();
        const x = (event.clientX - rect.left) * segmentationCanvas.width / rect.width;
        const y = (event.clientY - rect.top) * segmentationCanvas.height / rect.height;
        const mpp = Number(currentSceneData.meta.metersPerPixel) || 0.02;
        const hitRadius = Math.max(12, Math.min(28, segmentationCanvas.width * 0.025));
        let bestIndex = -1;
        let bestDistance = hitRadius;
        room.polygon.forEach((point, index) => {
            const distance = Math.hypot(point[0] / mpp - x, point[1] / mpp - y);
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
        const mpp = Number(currentSceneData.meta.metersPerPixel) || 0.02;
        const candidate = room.polygon.map(point => [...point]);
        candidate[polygonEditDragIndex] = [
            Math.max(0, (event.clientX - rect.left) * segmentationCanvas.width / rect.width) * mpp,
            Math.max(0, (event.clientY - rect.top) * segmentationCanvas.height / rect.height) * mpp,
        ];
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

    btnCancelScale.addEventListener("click", () => {
        scaleCalibrationActive = false;
        scaleCalibrationPoints = [];
        btnApplyScale.disabled = true;
        btnCalibrateScale.setAttribute("aria-pressed", "false");
        btnCalibrateScale.classList.remove("calibration-active");
        segmentationCanvas.classList.remove("calibration-crosshair");
        scaleCalibrationStatus.textContent = "Scale calibration cancelled.";
        if (loadedImageElement) render2DSegmentationCanvas();
    });

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
        if (floorPlanImages.length > 1) {
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
            if (levelIndex === 0) {
                const shift = [targetAnchor[0] - previousTarget[0], targetAnchor[1] - previousTarget[1]];
                const shiftPoint = point => [point[0] + shift[0], point[1] + shift[1]];
                currentSceneData.meta.levels.filter(level => Number(level.level ?? level.floorIndex) !== 0).forEach(level => {
                    const otherIndex = Number(level.level ?? level.floorIndex);
                    const isOtherFloor = item => Number(item.level ?? item.floorIndex) === otherIndex;
                    currentSceneData.rooms.filter(isOtherFloor).forEach(room => {
                        room.polygon = (room.polygon || []).map(shiftPoint);
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
            currentSceneData.meta.warnings = [...new Set([...(currentSceneData.meta.warnings || []), `Story ${levelIndex + 1} scale was recalibrated from two user-selected points and a known length.`])];
            labelMpp.textContent = `${newScale.toFixed(4)} m/px`;
            overlayScale.textContent = `Scale: ${newScale.toFixed(4)} m/px`;
            inputMpp.min = String(Math.min(0.005, newScale));
            inputMpp.max = String(Math.max(0.08, newScale));
            inputMpp.value = String(newScale);
            scaleCalibrationPoints = [];
            btnApplyScale.disabled = true;
            scaleCalibrationStatus.textContent = `Story ${levelIndex + 1} scale updated to ${newScale.toFixed(5)} m/px.`;
            refreshEditedScene();
            return;
        }
        const previousScale = Number(currentSceneData.meta.metersPerPixel) || 0.02;
        const factor = newScale / previousScale;
        const scalePoints = points => (points || []).map(([x, y]) => [x * factor, y * factor]);
        currentSceneData.rooms.forEach(room => {
            room.polygon = scalePoints(room.polygon);
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
        currentSceneData.meta.warnings = [...new Set([...(currentSceneData.meta.warnings || []), "Scale was recalibrated from two user-selected points and a known length."])];
        inputMpp.min = String(Math.min(0.005, newScale));
        inputMpp.max = String(Math.max(0.08, newScale));
        inputMpp.value = String(newScale);
        labelMpp.textContent = `${newScale.toFixed(4)} m/px`;
        overlayScale.textContent = `Scale: ${newScale.toFixed(4)} m/px`;
        scaleCalibrationPoints = [];
        btnApplyScale.disabled = true;
        scaleCalibrationStatus.textContent = `Scale updated to ${newScale.toFixed(5)} m/px.`;
        refreshEditedScene();
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
    btnLoadDemo.addEventListener("click", async () => {
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
            btnLoadDemo.textContent = "⚡ Load Hackathon Demo Plan";
        }
    });

    btnLoadTwoStoryDemo.addEventListener("click", async () => {
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
            btnLoadTwoStoryDemo.textContent = "🏢 Load Two-Story Demo";
        }
    });

    // -------------------------------------------------------------
    // Process uploads through a real job/status API.
    // -------------------------------------------------------------
    btnGenerate.addEventListener("click", async () => {
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
            formData.append("wallHeight", inputWallHeight.value);
            formData.append("wallThickness", inputWallThickness.value);

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

    btnProcessBuilding.addEventListener("click", async () => {
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
        floorPlanImages = Array.isArray(data.floorImages) ? data.floorImages : [];
        setProcessingBadge(currentSceneData.meta?.processingMode || "");
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

        // 1. Render in Three.js
        viewer.loadScene(data.scene);

        // 2. Populate scene.json viewer
        jsonOutput.textContent = JSON.stringify(data.scene, null, 2);

        // 3. Switch to 3D tab
        document.querySelector('[data-tab="3d"]').click();
        updateAreaSummary();
    }

    // -------------------------------------------------------------
    // 2D AI Segmentation Canvas Renderer
    // -------------------------------------------------------------
    function render2DSegmentationCanvas() {
        if (!loadedImageElement) return;

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
        const levelInfo = (currentSceneData.meta.levels || []).find(level => Number(level.level ?? level.floorIndex) === (overlayLevel ?? 0));
        const mpp = Number(levelInfo?.metersPerPixel) || Number(currentSceneData.meta.metersPerPixel) || 0.02;
        const belongsToSelectedLevel = item => selectedLevel === null
            ? (overlayLevel === null || (Number(item.level ?? item.floorIndex) || 0) === overlayLevel)
            : (Number(item.level ?? item.floorIndex) || 0) === selectedLevel;
        const sourcePoint = (item, point) => {
            const level = (currentSceneData.meta.levels || []).find(entry => Number(entry.level ?? entry.floorIndex) === (Number(item.level ?? item.floorIndex) || 0));
            const offset = level?.planOffset || [0, 0];
            return [point[0] - (Number(offset[0]) || 0), point[1] - (Number(offset[1]) || 0)];
        };

        // Draw Room Polygons
        (currentSceneData.rooms || []).filter(belongsToSelectedLevel).forEach(room => {
            const poly = room.polygon || [];
            if (poly.length < 3) return;

            segCtx.beginPath();
            const firstPoint = sourcePoint(room, poly[0]);
            segCtx.moveTo(firstPoint[0] / mpp, firstPoint[1] / mpp);
            for (let i = 1; i < poly.length; i++) {
                const point = sourcePoint(room, poly[i]);
                segCtx.lineTo(point[0] / mpp, point[1] / mpp);
            }
            segCtx.closePath();

            // Fill color matching room type
            segCtx.fillStyle = getRoomTypeCanvasColor(room.type);
            segCtx.fill();
            segCtx.strokeStyle = "#121212";
            segCtx.lineWidth = 3;
            segCtx.stroke();

            // Draw a square paper label with an ink outline.
            const [centroidX, centroidY] = sourcePoint(room, roomCentroid(room));
            const cx = centroidX / mpp;
            const cy = centroidY / mpp;

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
                    const x = point[0] / mpp;
                    const y = point[1] / mpp;
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
            const cx = sourceX / mpp;
            const cy = sourceY / mpp;
            const w = (door.width || 0.9) / mpp;

            segCtx.strokeStyle = "#D02020";
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.arc(cx, cy, w / 2, 0, Math.PI * 2);
            segCtx.stroke();
        });

        // Draw Windows
        (currentSceneData.windows || []).filter(belongsToSelectedLevel).forEach(win => {
            const [sourceX, sourceY] = sourcePoint(win, win.center || [0, 0]);
            const cx = sourceX / mpp;
            const cy = sourceY / mpp;
            const w = (win.width || 1.2) / mpp;

            segCtx.strokeStyle = "#1040C0";
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.moveTo(cx - w / 2, cy);
            segCtx.lineTo(cx + w / 2, cy);
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
        inspectorEmpty.classList.add("hidden");
        inspectorCard.classList.remove("hidden");

        inspectorTitle.textContent = room.label || `Room ${room.id}`;
        inspectorType.textContent = (room.type || "room").toUpperCase();
        
        const confidence = Number(room.confidence);
        inspectorConf.textContent = Number.isFinite(confidence) && confidence > 0
            ? `${Math.round(confidence * 100)}% Confidence`
            : "Unclassified";

        // Calculate approximate area in sq meters
        const poly = room.polygon || [];
        const area = polygonArea(poly);
        const sqft = area * 10.7639;
        inspectorArea.textContent = `${area.toFixed(1)} m² (${sqft.toFixed(0)} sq ft)`;
        inspectorPoints.textContent = `${poly.length} Vertices`;

        // Connected doors check
        if (currentSceneData && currentSceneData.doors) {
            const connected = currentSceneData.doors.filter(d => (d.connects || []).includes(room.id));
            if (connected.length > 0) {
                inspectorDoors.textContent = `${connected.length} Door(s) (${connected.map(d => d.id).join(", ")})`;
            } else {
                inspectorDoors.textContent = "None detected";
            }
        }

        editRoomName.value = room.label || "";
        const typeOption = Array.from(editRoomType.options).find(option => option.value === (room.type || "room"));
        if (!typeOption) editRoomType.add(new Option(room.type || "room", room.type || "room"));
        editRoomType.value = room.type || "room";
        [editRoomName, editRoomType, btnSaveRoomEdit, btnDeleteRoom, btnEditBoundary].forEach(control => { control.disabled = false; });
    };

    btnSaveRoomEdit.addEventListener("click", () => {
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

    btnDeleteRoom.addEventListener("click", () => {
        if (!currentSceneData || !selectedRoomId) return;
        const deletedId = selectedRoomId;
        currentSceneData.rooms = currentSceneData.rooms.filter(room => room.id !== deletedId);
        currentSceneData.doors = (currentSceneData.doors || []).map(door => ({
            ...door,
            connects: (door.connects || []).filter(roomId => roomId !== deletedId),
        })).filter(door => (door.connects || []).length > 0);
        refreshEditedScene();
        showMessage("Room removed from the scene. Export scene.json or GLB to keep the edit.", "warning");
    });

    // -------------------------------------------------------------
    // Copy & Download scene.json
    // -------------------------------------------------------------
    btnCopyJson.addEventListener("click", () => {
        if (!currentSceneData) return;
        navigator.clipboard.writeText(JSON.stringify(currentSceneData, null, 2))
            .then(() => {
                const originalText = btnCopyJson.textContent;
                btnCopyJson.textContent = "✓ Copied!";
                setTimeout(() => { btnCopyJson.textContent = originalText; }, 2000);
            })
            .catch(err => alert("Copy failed: " + err));
    });

    btnDownloadJson.addEventListener("click", () => {
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
});
