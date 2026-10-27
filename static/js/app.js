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
    const levelFilter = document.getElementById("level-filter");
    const appMessage = document.getElementById("app-message");
    const liveReady = document.body.dataset.liveReady === "true";
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

    // Room Inspector Drawer
    const inspectorCard = document.getElementById("room-inspector-card");
    const inspectorEmpty = document.getElementById("room-inspector-empty");
    const inspectorTitle = document.getElementById("inspector-title");
    const inspectorType = document.getElementById("inspector-type");
    const inspectorConf = document.getElementById("inspector-conf");
    const inspectorArea = document.getElementById("inspector-area");
    const inspectorPoints = document.getElementById("inspector-points");
    const inspectorDoors = document.getElementById("inspector-doors");

    // Application State
    let selectedFile = null;
    let currentSceneData = null;
    let currentOverlays = null;
    let loadedImageElement = null;
    let isCutawayActive = false;

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
        labelWallThickness.textContent = `${parseFloat(e.target.value).toFixed(2)} m`;
    });

    // -------------------------------------------------------------
    // Drag & Drop / File Selection
    // -------------------------------------------------------------
    dropZone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
            handleFileSelected(e.target.files[0]);
        }
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
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFileSelected(e.dataTransfer.files[0]);
        }
    });

    btnRemoveImage.addEventListener("click", (e) => {
        e.stopPropagation();
        selectedFile = null;
        fileInput.value = "";
        imagePreviewContainer.classList.add("hidden");
        dropZonePrompt.classList.remove("hidden");
        btnGenerate.disabled = true;
        clearMessage();
    });

    function handleFileSelected(file) {
        if (!["image/png", "image/jpeg", "image/webp"].includes(file.type.toLowerCase())) {
            showMessage("Choose a PNG, JPG, or WebP floor plan.", "error");
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            showMessage("The image must be 10 MB or smaller.", "error");
            return;
        }

        clearMessage();
        selectedFile = file;
        const reader = new FileReader();
        reader.onload = (event) => {
            imagePreview.src = event.target.result;
            imagePreviewContainer.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");
            btnGenerate.disabled = !liveReady;

            // Pre-load image for 2D canvas
            const img = new Image();
            img.onload = () => {
                loadedImageElement = img;
                if (currentSceneData) render2DSegmentationCanvas();
            };
            img.src = event.target.result;
        };
        reader.readAsDataURL(file);
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
            viewer.setWallHeight(originalHeight);
            labelWallHeight.textContent = `${originalHeight.toFixed(1)} m`;
        }
        viewer.setEyeLevelView();
    });
    btnViewReset.addEventListener("click", () => viewer.resetCameraView());
    levelFilter.addEventListener("change", () => {
        viewer.setVisibleLevel(levelFilter.value === "all" ? null : levelFilter.value);
        if (loadedImageElement) render2DSegmentationCanvas();
    });

    btnCutaway.addEventListener("click", () => {
        isCutawayActive = !isCutawayActive;
        if (isCutawayActive) {
            btnCutaway.classList.add("bg-amber-600", "text-white");
            btnCutaway.classList.remove("bg-slate-800", "text-slate-300");
            viewer.setWallHeight(1.1); // Cutaway height
            labelWallHeight.textContent = "1.1 m (Cutaway)";
        } else {
            btnCutaway.classList.remove("bg-amber-600", "text-white");
            btnCutaway.classList.add("bg-slate-800", "text-slate-300");
            const originalHeight = parseFloat(inputWallHeight.value) || 3.0;
            viewer.setWallHeight(originalHeight);
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
            if (data.scene.meta.warnings && data.scene.meta.warnings.length) {
                showMessage(data.scene.meta.warnings.join(" "), "warning");
            } else {
                showMessage("Floor plan processed successfully.");
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
            btnGenerate.disabled = !liveReady || !selectedFile;
        }
    });

    function handleProcessSuccess(data) {
        currentSceneData = data.scene;
        currentOverlays = data.overlays;
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
            const img = new Image();
            img.onload = () => {
                loadedImageElement = img;
                render2DSegmentationCanvas();
            };
            img.src = data.imageUrl;
        } else if (loadedImageElement) {
            render2DSegmentationCanvas();
        }

        // 1. Render in Three.js
        viewer.loadScene(data.scene);

        // 2. Populate scene.json viewer
        jsonOutput.textContent = JSON.stringify(data.scene, null, 2);

        // 3. Switch to 3D tab
        document.querySelector('[data-tab="3d"]').click();
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

        const mpp = currentSceneData.meta.metersPerPixel || 0.02;
        const selectedLevel = levelFilter.value === "all" ? null : Number(levelFilter.value);
        const belongsToSelectedLevel = item => selectedLevel === null
            || (Number(item.level ?? item.floorIndex) || 0) === selectedLevel;

        // Draw Room Polygons
        (currentSceneData.rooms || []).filter(belongsToSelectedLevel).forEach(room => {
            const poly = room.polygon || [];
            if (poly.length < 3) return;

            segCtx.beginPath();
            segCtx.moveTo(poly[0][0] / mpp, poly[0][1] / mpp);
            for (let i = 1; i < poly.length; i++) {
                segCtx.lineTo(poly[i][0] / mpp, poly[i][1] / mpp);
            }
            segCtx.closePath();

            // Fill color matching room type
            segCtx.fillStyle = getRoomTypeCanvasColor(room.type);
            segCtx.fill();
            segCtx.strokeStyle = "#121212";
            segCtx.lineWidth = 3;
            segCtx.stroke();

            // Draw a square paper label with an ink outline.
            const [centroidX, centroidY] = roomCentroid(room);
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

        // Draw Doors
        (currentSceneData.doors || []).filter(belongsToSelectedLevel).forEach(door => {
            const cx = (door.center ? door.center[0] : 0) / mpp;
            const cy = (door.center ? door.center[1] : 0) / mpp;
            const w = (door.width || 0.9) / mpp;

            segCtx.strokeStyle = "#D02020";
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.arc(cx, cy, w / 2, 0, Math.PI * 2);
            segCtx.stroke();
        });

        // Draw Windows
        (currentSceneData.windows || []).filter(belongsToSelectedLevel).forEach(win => {
            const cx = (win.center ? win.center[0] : 0) / mpp;
            const cy = (win.center ? win.center[1] : 0) / mpp;
            const w = (win.width || 1.2) / mpp;

            segCtx.strokeStyle = "#1040C0";
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.moveTo(cx - w / 2, cy);
            segCtx.lineTo(cx + w / 2, cy);
            segCtx.stroke();
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
        inspectorEmpty.classList.add("hidden");
        inspectorCard.classList.remove("hidden");

        inspectorTitle.textContent = room.label || `Room ${room.id}`;
        inspectorType.textContent = (room.type || "room").toUpperCase();
        
        const confidence = Number(room.confidence);
        inspectorConf.textContent = Number.isFinite(confidence) && confidence > 0
            ? `${Math.round(confidence * 100)}% Confidence`
            : "Unclassified";

        // Calculate approximate area in sq meters
        let area = 0;
        const poly = room.polygon || [];
        if (poly.length >= 3) {
            for (let i = 0; i < poly.length; i++) {
                const j = (i + 1) % poly.length;
                area += poly[i][0] * poly[j][1];
                area -= poly[j][0] * poly[i][1];
            }
            area = Math.abs(area) / 2.0;
        }
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
    };

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
