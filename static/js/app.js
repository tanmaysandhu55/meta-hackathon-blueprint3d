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
    const progressContainer = document.getElementById("progress-container");
    const progressBar = document.getElementById("progress-bar");
    const progressStatus = document.getElementById("progress-status");

    // Sliders
    const inputMpp = document.getElementById("input-mpp");
    const labelMpp = document.getElementById("label-mpp");
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

    // JSON Viewer & Actions
    const jsonOutput = document.getElementById("json-output");
    const btnCopyJson = document.getElementById("btn-copy-json");
    const btnDownloadJson = document.getElementById("btn-download-json");
    const btnExportGlb = document.getElementById("btn-export-glb");
    const btnDownloadGlbTab = document.getElementById("btn-download-glb-tab");

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

    // -------------------------------------------------------------
    // Slider Events
    // -------------------------------------------------------------
    inputMpp.addEventListener("input", (e) => {
        labelMpp.textContent = `${parseFloat(e.target.value).toFixed(3)} m/px`;
    });

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
    });

    function handleFileSelected(file) {
        if (!file.type.startsWith("image/")) {
            alert("Please select a valid image file (PNG, JPG, WEBP).");
            return;
        }

        selectedFile = file;
        const reader = new FileReader();
        reader.onload = (event) => {
            imagePreview.src = event.target.result;
            imagePreviewContainer.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");
            btnGenerate.disabled = false;

            // Pre-load image for 2D canvas
            const img = new Image();
            img.onload = () => { loadedImageElement = img; };
            img.src = event.target.result;
        };
        reader.readAsDataURL(file);
    }

    // -------------------------------------------------------------
    // Camera Presets & Layer Toggles
    // -------------------------------------------------------------
    btnViewIso.addEventListener("click", () => viewer.setPerspectiveView());
    btnViewTop.addEventListener("click", () => viewer.setTopDownView());
    btnViewEye.addEventListener("click", () => viewer.setEyeLevelView());
    btnViewReset.addEventListener("click", () => viewer.resetCameraView());

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

            const res = await fetch("/api/sample");
            const data = await res.json();

            if (!data.success) {
                throw new Error(data.error || "Failed to load demo floor plan.");
            }

            // Update UI with demo data
            imagePreview.src = data.imageUrl;
            imagePreviewContainer.classList.remove("hidden");
            dropZonePrompt.classList.add("hidden");

            // Cache image for 2D overlay
            const img = new Image();
            img.onload = () => {
                loadedImageElement = img;
                render2DSegmentationCanvas();
            };
            img.src = data.imageUrl;

            // Load into 3D viewer
            handleProcessSuccess(data);

        } catch (err) {
            alert(`Demo load error: ${err.message}`);
        } finally {
            btnLoadDemo.disabled = false;
            btnLoadDemo.textContent = "⚡ Load Hackathon Demo Plan";
        }
    });

    // -------------------------------------------------------------
    // Process User Upload with Live Progress Animation
    // -------------------------------------------------------------
    btnGenerate.addEventListener("click", async () => {
        if (!selectedFile) {
            alert("Please select a floor plan image first.");
            return;
        }

        btnGenerate.disabled = true;
        progressContainer.classList.remove("hidden");

        const steps = [
            { pct: 15, text: "Uploading 2D floor plan..." },
            { pct: 35, text: "Baseten API: Meta SAM 3.1 segmenting rooms, walls, doors, windows..." },
            { pct: 65, text: "OpenCV & Shapely: Snapping polygons to meters..." },
            { pct: 85, text: "Modal & Fireworks: Muse Spark & Meta Llama 3 classifying regions..." },
            { pct: 95, text: "Three.js: Constructing 3D geometry..." },
        ];

        let stepIndex = 0;
        const progressTimer = setInterval(() => {
            if (stepIndex < steps.length) {
                progressBar.style.width = `${steps[stepIndex].pct}%`;
                progressStatus.textContent = steps[stepIndex].text;
                stepIndex++;
            }
        }, 1200);

        try {
            const formData = new FormData();
            formData.append("file", selectedFile);
            formData.append("metersPerPixel", inputMpp.value);
            formData.append("wallHeight", inputWallHeight.value);
            formData.append("wallThickness", inputWallThickness.value);

            const response = await fetch("/api/process", {
                method: "POST",
                body: formData
            });

            clearInterval(progressTimer);
            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to process floor plan.");
            }

            progressBar.style.width = "100%";
            progressStatus.textContent = "3D Map Generated Successfully!";

            setTimeout(() => {
                progressContainer.classList.add("hidden");
                progressBar.style.width = "0%";
            }, 1000);

            handleProcessSuccess(data);

        } catch (err) {
            clearInterval(progressTimer);
            progressContainer.classList.add("hidden");
            progressBar.style.width = "0%";
            alert(`Processing Error:\n${err.message}`);
        } finally {
            btnGenerate.disabled = false;
        }
    });

    function handleProcessSuccess(data) {
        currentSceneData = data.scene;
        currentOverlays = data.overlays;

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

        // Draw Room Polygons
        (currentSceneData.rooms || []).forEach(room => {
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
            segCtx.strokeStyle = "#3b82f6";
            segCtx.lineWidth = 2;
            segCtx.stroke();

            // Draw label pill
            const cx = poly.reduce((acc, p) => acc + p[0], 0) / poly.length / mpp;
            const cy = poly.reduce((acc, p) => acc + p[1], 0) / poly.length / mpp;

            segCtx.fillStyle = "rgba(15, 23, 42, 0.85)";
            segCtx.fillRect(cx - 50, cy - 14, 100, 24);
            segCtx.fillStyle = "#ffffff";
            segCtx.font = "bold 12px 'Inter', sans-serif";
            segCtx.textAlign = "center";
            segCtx.fillText(room.label || room.id, cx, cy + 2);
        });

        // Draw Doors
        (currentSceneData.doors || []).forEach(door => {
            const cx = (door.center ? door.center[0] : 0) / mpp;
            const cy = (door.center ? door.center[1] : 0) / mpp;
            const w = (door.width || 0.9) / mpp;

            segCtx.strokeStyle = "#f59e0b"; // Amber door
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.arc(cx, cy, w / 2, 0, Math.PI * 2);
            segCtx.stroke();
        });

        // Draw Windows
        (currentSceneData.windows || []).forEach(win => {
            const cx = (win.center ? win.center[0] : 0) / mpp;
            const cy = (win.center ? win.center[1] : 0) / mpp;
            const w = (win.width || 1.2) / mpp;

            segCtx.strokeStyle = "#38bdf8"; // Cyan window
            segCtx.lineWidth = 4;
            segCtx.beginPath();
            segCtx.moveTo(cx - w / 2, cy);
            segCtx.lineTo(cx + w / 2, cy);
            segCtx.stroke();
        });
    }

    function getRoomTypeCanvasColor(type) {
        const colors = {
            classroom: "rgba(59, 130, 246, 0.35)",
            lab:       "rgba(139, 92, 246, 0.35)",
            corridor:  "rgba(100, 116, 139, 0.35)",
            restroom:  "rgba(20, 184, 166, 0.35)",
            stairs:    "rgba(245, 158, 11, 0.35)",
            elevator:  "rgba(249, 115, 22, 0.35)",
            entrance:  "rgba(16, 185, 129, 0.35)",
            room:      "rgba(71, 85, 105, 0.35)",
            other:     "rgba(148, 163, 184, 0.35)"
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
        
        const confVal = Math.round((room.confidence || 0.9) * 100);
        inspectorConf.textContent = `${confVal}% Confidence`;

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
        URL.revokeObjectURL(url);
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
