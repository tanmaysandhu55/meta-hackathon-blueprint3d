/**
 * FloorPlan3D - Three.js 3D Interactive Floor Plan Viewer
 * 
 * Renders scene.json (METERS, origin top-left of plan, x right, y down) as a navigable 3D map.
 * Features:
 * - Extruded 3D walls with hole cutouts (real-time height adjustment)
 * - Color-coded room floor slabs based on room types
 * - 3D floating canvas text badges for room labels, types, and confidence scores
 * - 3D door openings and glass windows
 * - Interactive raycasting: click any room to inspect dimensions, area, and connections
 * - Multiple camera modes (Isometric 3D, Top-Down 2D, Eye-Level Orbit)
 * - Measurement grid and scale bar in meters
 * - Layer visibility toggles (walls, floors, labels, doors, grid)
 */

class FloorPlanViewer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`Container #${containerId} not found.`);
            return;
        }

        // Core Three.js components
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();

        // 3D Object groups for clean layer toggling
        this.groups = {
            walls: new THREE.Group(),
            rooms: new THREE.Group(),
            labels: new THREE.Group(),
            doors: new THREE.Group(),
            windows: new THREE.Group(),
            grid: new THREE.Group(),
        };

        // Scene state & metadata
        this.currentSceneData = null;
        this.centerOffset = { x: 0, y: 0 };
        this.selectedRoomMesh = null;
        this.selectedRoomOriginalColor = null;
        this.wallHeight = 3.0; // default in meters
        this.is2DMode = false;

        // Color palette for room types (modern architectural pastel tones)
        this.roomColors = {
            classroom: 0x3b82f6, // Vibrant Blue
            lab:       0x8b5cf6, // Modern Purple
            corridor:  0x64748b, // Slate Neutral
            restroom:  0x14b8a6, // Fresh Teal
            stairs:    0xf59e0b, // Amber
            elevator:  0xf97316, // Orange
            entrance:  0x10b981, // Emerald Green
            room:      0x475569, // Architecture Gray
            other:     0x94a3b8, // Light Cool Gray
        };

        // Initialize WebGL scene
        this.init();
    }

    init() {
        const width = this.container.clientWidth || 800;
        const height = this.container.clientHeight || 600;

        // 1. Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x0b132b); // Deep architectural navy

        // 2. Camera (Perspective)
        this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
        this.camera.position.set(15, 20, 20);

        // 3. WebGL Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.container.appendChild(this.renderer.domElement);

        // 4. OrbitControls (pinned CDN)
        this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.maxPolarAngle = Math.PI / 2 + 0.05; // Do not go below ground
        this.controls.minDistance = 2;
        this.controls.maxDistance = 150;

        // 5. Lighting Setup (Soft architectural illumination)
        this.setupLighting();

        // 6. Add object groups to scene
        Object.values(this.groups).forEach(g => this.scene.add(g));

        // 7. Event Listeners
        window.addEventListener("resize", () => this.onWindowResize());
        this.renderer.domElement.addEventListener("click", (e) => this.onPointerClick(e));

        // 8. Start Render Loop
        this.animate();
    }

    setupLighting() {
        // Soft ambient fill light
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
        this.scene.add(ambientLight);

        // Hemisphere light: subtle blue sky vs warm bounce ground
        const hemiLight = new THREE.HemisphereLight(0xe0f2fe, 0x1e293b, 0.5);
        hemiLight.position.set(0, 50, 0);
        this.scene.add(hemiLight);

        // Key directional light with soft architectural shadows
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.85);
        dirLight.position.set(30, 45, 25);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.width = 2048;
        dirLight.shadow.mapSize.height = 2048;
        dirLight.shadow.camera.near = 1;
        dirLight.shadow.camera.far = 150;
        const d = 35;
        dirLight.shadow.camera.left = -d;
        dirLight.shadow.camera.right = d;
        dirLight.shadow.camera.top = d;
        dirLight.shadow.camera.bottom = -d;
        dirLight.shadow.bias = -0.0005;
        this.scene.add(dirLight);

        // Soft secondary fill light
        const fillLight = new THREE.DirectionalLight(0x93c5fd, 0.35);
        fillLight.position.set(-25, 25, -20);
        this.scene.add(fillLight);
    }

    /**
     * Loads and renders a complete scene.json contract.
     * @param {Object} sceneData 
     */
    loadScene(sceneData) {
        if (!sceneData || !sceneData.meta) {
            console.error("Invalid scene.json provided:", sceneData);
            return;
        }

        this.currentSceneData = sceneData;
        this.wallHeight = sceneData.meta.wallHeight || 3.0;

        // Clear existing geometries
        this.clear();

        // 1. Calculate bounding box of all coordinates to center the model at (0, 0, 0)
        this.calculateCenterOffset(sceneData);

        // 2. Build 3D elements
        this.buildGroundAndGrid();
        this.buildRooms(sceneData.rooms || []);
        this.buildWalls(sceneData.walls || []);
        this.buildDoors(sceneData.doors || []);
        this.buildWindows(sceneData.windows || []);

        // 3. Position camera nicely around building center
        this.resetCameraView();
    }

    clear() {
        Object.values(this.groups).forEach(g => {
            while (g.children.length > 0) {
                const obj = g.children[0];
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) {
                    if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
                    else obj.material.dispose();
                }
                g.remove(obj);
            }
        });
        this.selectedRoomMesh = null;
        this.selectedRoomOriginalColor = null;
    }

    calculateCenterOffset(sceneData) {
        let minX = Infinity, maxX = -Infinity;
        let minY = Infinity, maxY = -Infinity;

        const checkCoord = (x, y) => {
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        };

        // Scan rooms
        (sceneData.rooms || []).forEach(r => {
            (r.polygon || []).forEach(pt => checkCoord(pt[0], pt[1]));
        });

        // Scan walls
        (sceneData.walls || []).forEach(w => {
            (w.polygon || []).forEach(pt => checkCoord(pt[0], pt[1]));
        });

        if (minX === Infinity) {
            minX = 0; maxX = 16;
            minY = 0; maxY = 12;
        }

        this.bounds = { minX, maxX, minY, maxY, width: maxX - minX, height: maxY - minY };
        this.centerOffset = {
            x: (minX + maxX) / 2.0,
            y: (minY + maxY) / 2.0
        };
    }

    /**
     * Converts a 2D scene.json coordinate [x, y] in meters
     * into 3D world coordinates centered at (0, 0, 0).
     */
    toWorldCoords(x, y) {
        return {
            x: x - this.centerOffset.x,
            z: y - this.centerOffset.y
        };
    }

    buildGroundAndGrid() {
        const span = Math.max(this.bounds.width, this.bounds.height, 20);
        const gridSize = Math.ceil(span * 1.8);
        const divisions = gridSize; // 1 division = exactly 1 meter!

        // 1-meter architectural grid helper
        const grid = new THREE.GridHelper(gridSize, divisions, 0x3b82f6, 0x1e293b);
        grid.position.y = -0.01;
        this.groups.grid.add(grid);

        // Ground foundation plane
        const groundGeo = new THREE.PlaneGeometry(gridSize * 1.5, gridSize * 1.5);
        const groundMat = new THREE.MeshStandardMaterial({
            color: 0x070d1e,
            roughness: 0.9,
            metalness: 0.1
        });
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.02;
        ground.receiveShadow = true;
        this.groups.grid.add(ground);
    }

    /**
     * Builds extruded 3D walls from scene.json walls array.
     * Supports holes (openings) and dynamic height updates.
     */
    buildWalls(walls) {
        const wallMat = new THREE.MeshStandardMaterial({
            color: 0xe2e8f0,      // Architectural clean off-white / light slate
            roughness: 0.5,
            metalness: 0.05,
            side: THREE.DoubleSide
        });

        walls.forEach(wall => {
            const poly = wall.polygon || [];
            if (poly.length < 3) return;

            // In our mathematical mapping:
            // u = x - Cx, v = -(y - Cy)
            // Extrude along +z, then rotateX(-Math.PI / 2):
            // Results in X = x - Cx, Y = height (0 to wallHeight), Z = y - Cy!
            const shape = new THREE.Shape();
            const p0 = this.toWorldCoords(poly[0][0], poly[0][1]);
            shape.moveTo(p0.x, -p0.z);

            for (let i = 1; i < poly.length; i++) {
                const pt = this.toWorldCoords(poly[i][0], poly[i][1]);
                shape.lineTo(pt.x, -pt.z);
            }
            shape.closePath();

            // Add holes if any exist in the wall polygon
            if (wall.holes && wall.holes.length > 0) {
                wall.holes.forEach(holePoly => {
                    if (holePoly.length < 3) return;
                    const holePath = new THREE.Path();
                    const hp0 = this.toWorldCoords(holePoly[0][0], holePoly[0][1]);
                    holePath.moveTo(hp0.x, -hp0.z);
                    for (let j = 1; j < holePoly.length; j++) {
                        const hpt = this.toWorldCoords(holePoly[j][0], holePoly[j][1]);
                        holePath.lineTo(hpt.x, -hpt.z);
                    }
                    holePath.closePath();
                    shape.holes.push(holePath);
                });
            }

            const extrudeSettings = {
                depth: this.wallHeight,
                bevelEnabled: false,
                steps: 1
            };

            const wallGeom = new THREE.ExtrudeGeometry(shape, extrudeSettings);
            wallGeom.rotateX(-Math.PI / 2); // Rotate extrusion vertically along +Y

            const wallMesh = new THREE.Mesh(wallGeom, wallMat);
            wallMesh.castShadow = true;
            wallMesh.receiveShadow = true;
            wallMesh.userData = { isWall: true, wallId: wall.id };

            this.groups.walls.add(wallMesh);
        });
    }

    /**
     * Builds floor slabs and floating label badges for each room.
     */
    buildRooms(rooms) {
        rooms.forEach(room => {
            const poly = room.polygon || [];
            if (poly.length < 3) return;

            const shape = new THREE.Shape();
            const p0 = this.toWorldCoords(poly[0][0], poly[0][1]);
            shape.moveTo(p0.x, -p0.z);

            let sumX = p0.x;
            let sumZ = p0.z;

            for (let i = 1; i < poly.length; i++) {
                const pt = this.toWorldCoords(poly[i][0], poly[i][1]);
                shape.lineTo(pt.x, -pt.z);
                sumX += pt.x;
                sumZ += pt.z;
            }
            shape.closePath();

            // Room floor geometry
            const roomGeo = new THREE.ShapeGeometry(shape);
            roomGeo.rotateX(-Math.PI / 2); // Lay flat on ground

            // Pick color based on room type
            const colorHex = this.roomColors[room.type] || this.roomColors.other;
            const roomMat = new THREE.MeshStandardMaterial({
                color: colorHex,
                roughness: 0.65,
                metalness: 0.1,
                side: THREE.DoubleSide
            });

            const roomMesh = new THREE.Mesh(roomGeo, roomMat);
            roomMesh.position.y = 0.02; // Slightly above ground to prevent z-fighting
            roomMesh.receiveShadow = true;
            roomMesh.userData = {
                isRoom: true,
                roomData: room,
                originalColor: colorHex
            };

            this.groups.rooms.add(roomMesh);

            // Calculate centroid for floating label badge
            const centroidX = sumX / poly.length;
            const centroidZ = sumZ / poly.length;

            // Create floating 3D text badge
            const badgeSprite = this.createRoomBadgeSprite(room);
            badgeSprite.position.set(centroidX, 1.4, centroidZ);
            this.groups.labels.add(badgeSprite);
        });
    }

    /**
     * Creates an architectural text badge sprite using an HTML5 2D canvas.
     */
    createRoomBadgeSprite(room) {
        const canvas = document.createElement("canvas");
        canvas.width = 512;
        canvas.height = 256;
        const ctx = canvas.getContext("2d");

        // High DPI sharpness
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Badge background card (rounded rectangle)
        const x = 32, y = 32, w = 448, h = 192, radius = 24;
        ctx.fillStyle = "rgba(15, 23, 42, 0.92)";
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + w - radius, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
        ctx.lineTo(x + w, y + h - radius);
        ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
        ctx.lineTo(x + radius, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
        ctx.fill();

        // Color border matching room type
        const typeColorHex = this.roomColors[room.type] || 0x3b82f6;
        const hexStr = "#" + typeColorHex.toString(16).padStart(6, "0");
        ctx.strokeStyle = hexStr;
        ctx.lineWidth = 6;
        ctx.stroke();

        // Type color accent pill
        ctx.fillStyle = hexStr;
        ctx.beginPath();
        ctx.roundRect ? ctx.roundRect(56, 52, 12, 40, 6) : ctx.rect(56, 52, 12, 40);
        ctx.fill();

        // Main Room Label Text
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 36px 'Inter', sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(room.label || `Room ${room.id}`, 80, 84);

        // Subtitle: Room Type and Confidence
        ctx.fillStyle = "#94a3b8";
        ctx.font = "500 24px 'Inter', sans-serif";
        const typeCapitalized = (room.type || "room").toUpperCase();
        const confPercent = Math.round((room.confidence || 0.9) * 100);
        ctx.fillText(`${typeCapitalized} • ${confPercent}% Conf`, 80, 140);

        // Badge sprite texture
        const texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;
        texture.generateMipmaps = false;

        const spriteMat = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            depthTest: false // Always visible above walls
        });

        const sprite = new THREE.Sprite(spriteMat);
        sprite.scale.set(3.2, 1.6, 1.0);
        return sprite;
    }

    /**
     * Builds 3D door openings and subtle swinging door panels.
     */
    buildDoors(doors) {
        const doorFrameMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.5 });
        const doorPanelMat = new THREE.MeshStandardMaterial({ color: 0xb45309, roughness: 0.4 }); // Warm wood finish

        doors.forEach(door => {
            const center = door.center || [0, 0];
            const pt = this.toWorldCoords(center[0], center[1]);
            const width = Math.max(0.6, door.width || 0.9);
            const doorHeight = 2.1; // Standard door height in meters

            // Door frame group
            const doorGroup = new THREE.Group();
            doorGroup.position.set(pt.x, 0, pt.z);

            // Thin semi-open wooden panel
            const panelGeo = new THREE.BoxGeometry(width * 0.95, doorHeight, 0.04);
            const panelMesh = new THREE.Mesh(panelGeo, doorPanelMat);
            panelMesh.position.set(width * 0.4, doorHeight / 2, width * 0.2);
            panelMesh.rotation.y = Math.PI / 4; // 45-degree welcoming open swing
            panelMesh.castShadow = true;
            doorGroup.add(panelMesh);

            this.groups.doors.add(doorGroup);
        });
    }

    /**
     * Builds translucent glass windows and architectural window frames.
     */
    buildWindows(windows) {
        const glassMat = new THREE.MeshStandardMaterial({
            color: 0x38bdf8,       // Sky blue architectural glass
            transparent: true,
            opacity: 0.45,
            roughness: 0.1,
            metalness: 0.2
        });
        const frameMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5 });

        windows.forEach(win => {
            const center = win.center || [0, 0];
            const pt = this.toWorldCoords(center[0], center[1]);
            const width = Math.max(0.8, win.width || 1.2);
            const winHeight = 1.2;
            const sillHeight = 0.9; // standard 0.9m above floor

            const winGroup = new THREE.Group();
            winGroup.position.set(pt.x, sillHeight + winHeight / 2, pt.z);

            // Glass pane
            const glassGeo = new THREE.BoxGeometry(width, winHeight, 0.04);
            const glassMesh = new THREE.Mesh(glassGeo, glassMat);
            winGroup.add(glassMesh);

            // Top and bottom sills
            const sillGeo = new THREE.BoxGeometry(width * 1.05, 0.06, 0.12);
            const topSill = new THREE.Mesh(sillGeo, frameMat);
            topSill.position.y = winHeight / 2;
            const botSill = new THREE.Mesh(sillGeo, frameMat);
            botSill.position.y = -winHeight / 2;
            winGroup.add(topSill);
            winGroup.add(botSill);

            this.groups.windows.add(winGroup);
        });
    }

    /**
     * Interactively updates wall height across all walls.
     */
    setWallHeight(heightMeters) {
        if (!this.currentSceneData) return;
        this.wallHeight = Math.max(0.2, parseFloat(heightMeters) || 3.0);
        
        // Rebuild only the walls layer
        while (this.groups.walls.children.length > 0) {
            const obj = this.groups.walls.children[0];
            if (obj.geometry) obj.geometry.dispose();
            this.groups.walls.remove(obj);
        }
        this.buildWalls(this.currentSceneData.walls || []);
    }

    /**
     * Raycasting click handler: highlights selected room and notifies UI.
     */
    onPointerClick(event) {
        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.groups.rooms.children, true);

        if (intersects.length > 0) {
            const hitMesh = intersects[0].object;
            if (hitMesh.userData && hitMesh.userData.isRoom) {
                this.selectRoom(hitMesh);
            }
        }
    }

    selectRoom(roomMesh) {
        // Reset previously selected room color
        if (this.selectedRoomMesh && this.selectedRoomOriginalColor !== null) {
            this.selectedRoomMesh.material.color.setHex(this.selectedRoomOriginalColor);
            this.selectedRoomMesh.material.emissive.setHex(0x000000);
        }

        this.selectedRoomMesh = roomMesh;
        this.selectedRoomOriginalColor = roomMesh.userData.originalColor;

        // Highlight with bright golden emissive glow
        roomMesh.material.color.setHex(0xfbbf24);
        roomMesh.material.emissive.setHex(0xd97706);

        // Notify global UI handler
        if (typeof window.onFloorPlanRoomSelected === "function") {
            window.onFloorPlanRoomSelected(roomMesh.userData.roomData);
        }
    }

    /**
     * Camera View Presets
     */
    setPerspectiveView() {
        this.is2DMode = false;
        const span = Math.max(this.bounds ? this.bounds.width : 20, this.bounds ? this.bounds.height : 20, 20);
        this.controls.target.set(0, 0, 0);
        this.camera.position.set(span * 0.8, span * 0.9, span * 0.8);
        this.controls.maxPolarAngle = Math.PI / 2 + 0.05;
        this.controls.update();
    }

    setTopDownView() {
        this.is2DMode = true;
        const span = Math.max(this.bounds ? this.bounds.width : 20, this.bounds ? this.bounds.height : 20, 20);
        this.controls.target.set(0, 0, 0);
        this.camera.position.set(0, span * 1.6, 0.01); // Look straight down
        this.controls.update();
    }

    setEyeLevelView() {
        this.is2DMode = false;
        this.controls.target.set(0, 1.2, 0);
        this.camera.position.set(0, 1.7, 8);
        this.controls.update();
    }

    resetCameraView() {
        this.setPerspectiveView();
    }

    /**
     * Layer Visibility Toggles
     */
    toggleLayer(layerName, isVisible) {
        if (this.groups[layerName]) {
            this.groups[layerName].visible = isVisible;
        }
    }

    /**
     * Exports the rendered 3D architectural scene as a standard binary .GLB file.
     * Can be opened in Blender, Windows 3D Viewer, Unity, Unreal Engine, etc.
     */
    exportGLB(filename = "floorplan3d_model.glb") {
        if (!THREE.GLTFExporter) {
            alert("GLTFExporter is not loaded.");
            return;
        }

        // Build a clean export container including walls, floors, doors, and windows
        const exportScene = new THREE.Scene();
        const exportGroups = [this.groups.walls, this.groups.rooms, this.groups.doors, this.groups.windows];

        exportGroups.forEach(group => {
            group.children.forEach(child => {
                if (child.isMesh || child.isGroup) {
                    exportScene.add(child.clone(true));
                }
            });
        });

        const exporter = new THREE.GLTFExporter();
        exporter.parse(
            exportScene,
            (arrayBuffer) => {
                if (arrayBuffer instanceof ArrayBuffer) {
                    const blob = new Blob([arrayBuffer], { type: "model/gltf-binary" });
                    const link = document.createElement("a");
                    link.href = URL.createObjectURL(blob);
                    link.download = filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    URL.revokeObjectURL(link.href);
                } else {
                    console.error("Export produced non-binary output:", arrayBuffer);
                }
            },
            { binary: true, embedImages: true }
        );
    }

    onWindowResize() {
        if (!this.container || !this.renderer || !this.camera) return;
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    }

    animate() {
        requestAnimationFrame(() => this.animate());
        if (this.controls) this.controls.update();
        if (this.renderer && this.scene && this.camera) {
            this.renderer.render(this.scene, this.camera);
        }
    }
}
