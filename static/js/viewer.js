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
            grid: new THREE.Group(),
            route: new THREE.Group(),
        };
        this.floorGroups = new Map();
        this.floorLayerNames = ["walls", "rooms", "labels", "doors", "windows"];
        this.layerVisibility = Object.fromEntries(this.floorLayerNames.map(name => [name, true]));
        this.selectableMeshes = [];

        // Scene state & metadata
        this.currentSceneData = null;
        this.centerOffset = { x: 0, y: 0 };
        this.selectedRoomMesh = null;
        this.selectedRoomOriginalColor = null;
        this.wallHeight = 3.0; // default in meters
        this.floorHeight = 3.2;
        this.levelCount = 1;
        this.sceneHeight = this.wallHeight;
        this.visibleLevel = null;
        this.is2DMode = false;
        this.isEyeLevelView = false;
        this.currentIsolatedFloor = null;
        this.pendingFloorIsolation = null;
        this.isolationTween = null;
        this.loadingGroup = null;
        this.loadingLaser = null;
        this.animatingMeshes = [];

        // Room categories use the Bauhaus primary palette plus paper and ink.
        this.roomColors = {
            classroom: 0x1040c0,
            lab:       0xd02020,
            corridor:  0xe0e0e0,
            restroom:  0x1040c0,
            stairs:    0xf0c020,
            elevator: 0xd02020,
            entrance: 0xf0c020,
            room:      0xe0e0e0,
            other:     0xe0e0e0,
        };

        // Initialize WebGL scene
        this.init();
    }

    init() {
        const width = this.container.clientWidth || 800;
        const height = this.container.clientHeight || 600;

        // 1. Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x1040c0); // Bauhaus blue viewport field

        // 2. Camera (Perspective)
        this.camera = new THREE.PerspectiveCamera(45, width / height, 0.05, 1000);
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
        this.createFloorInfoPanel();

        // 7. Event Listeners
        window.addEventListener("resize", () => this.onWindowResize());
        window.addEventListener("keydown", (event) => this.panWithArrowKeys(event));
        this.renderer.domElement.addEventListener("click", (e) => this.onPointerClick(e));

        // 8. Start Render Loop
        this.animate();
    }

    setupLighting() {
        // Soft ambient fill light
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.45);
        this.scene.add(ambientLight);

        // Hemisphere light: subtle blue sky vs warm bounce ground
        const hemiLight = new THREE.HemisphereLight(0xf0f0f0, 0x121212, 0.65);
        hemiLight.position.set(0, 50, 0);
        this.scene.add(hemiLight);

        // Key directional light with soft architectural shadows
        const dirLight = new THREE.DirectionalLight(0xffffff, 1.15);
        dirLight.position.set(30, 45, 25);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.width = 4096;
        dirLight.shadow.mapSize.height = 4096;
        dirLight.shadow.camera.near = 1;
        dirLight.shadow.camera.far = 150;
        const d = 35;
        dirLight.shadow.camera.left = -d;
        dirLight.shadow.camera.right = d;
        dirLight.shadow.camera.top = d;
        dirLight.shadow.camera.bottom = -d;
        dirLight.shadow.bias = -0.00025;
        dirLight.shadow.normalBias = 0.025;
        dirLight.shadow.radius = 4;
        this.keyLight = dirLight;
        this.scene.add(dirLight);
        this.scene.add(dirLight.target);

        // Soft secondary fill light
        const fillLight = new THREE.DirectionalLight(0x1040c0, 0.25);
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
        this.wallHeight = Number(sceneData.meta.wallHeight) || 3.0;
        this.floorHeight = Number(sceneData.meta.floorHeight) || this.wallHeight;
        this.levelCount = Math.max(1, Number(sceneData.meta.levelCount) || (sceneData.meta.levels || []).length || 1);
        const declaredElevations = (sceneData.meta.levels || []).map(level => Number(level.elevation)).filter(Number.isFinite);
        const highestFloor = declaredElevations.length
            ? Math.max(...declaredElevations)
            : (this.levelCount - 1) * this.floorHeight;
        this.sceneHeight = highestFloor + this.wallHeight;
        this.visibleLevel = null;
        this.currentIsolatedFloor = null;
        this.pendingFloorIsolation = null;
        this.isolationTween = null;
        this.selectableMeshes = [];
        this.animatingMeshes = [];
        this.hideFloorInfoPanel();

        // Clear existing geometries
        this.clear();

        // 1. Calculate bounding box of all coordinates to center the model at (0, 0, 0)
        this.calculateCenterOffset(sceneData);
        this.configureShadowCamera();
        this.createFloorGroups(sceneData);

        // 2. Build 3D elements
        this.buildGroundAndGrid();
        this.buildRooms(sceneData.rooms || []);
        this.hideLoadingState();
        this.buildWalls(sceneData.walls || []);
        this.buildDoors(sceneData.doors || []);
        this.buildWindows(sceneData.windows || []);

        this.updateVisibleLevels();
        this.refreshSelectableMeshes();

        // 3. Position camera nicely around building center
        this.resetCameraView();
    }

    showLoadingState() {
        if (!this.scene) return;
        this.hideLoadingState();

        const loadingGroup = new THREE.Group();
        loadingGroup.name = "loadingGroup";

        const blueprintGrid = new THREE.GridHelper(20, 20, 0xf0c020, 0x121212);
        loadingGroup.add(blueprintGrid);

        const laserGeometry = new THREE.PlaneGeometry(20, 0.2);
        const laserMaterial = new THREE.MeshStandardMaterial({
            color: 0xd02020,
            emissive: 0xd02020,
            emissiveIntensity: 0.65,
            transparent: true,
            opacity: 0.8,
            side: THREE.DoubleSide,
            depthWrite: false
        });
        const laser = new THREE.Mesh(laserGeometry, laserMaterial);
        laser.rotation.x = -Math.PI / 2;
        laser.position.y = 0.04;
        loadingGroup.add(laser);

        this.loadingGroup = loadingGroup;
        this.loadingLaser = laser;
        this.scene.add(loadingGroup);
    }

    hideLoadingState() {
        if (!this.loadingGroup) return;
        this.scene?.remove(this.loadingGroup);
        this.loadingGroup.traverse(object => {
            if (object.geometry) object.geometry.dispose();
            if (object.material) {
                const materials = Array.isArray(object.material) ? object.material : [object.material];
                materials.forEach(material => {
                    if (material.map) material.map.dispose();
                    material.dispose();
                });
            }
        });
        this.loadingGroup = null;
        this.loadingLaser = null;
    }

    disposeObjectResources(root) {
        const geometries = new Set();
        const materials = new Set();
        const textures = new Set();
        root.traverse(object => {
            if (object.geometry) geometries.add(object.geometry);
            const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
            objectMaterials.filter(Boolean).forEach(material => {
                materials.add(material);
                Object.values(material).forEach(value => {
                    if (value?.isTexture) textures.add(value);
                });
            });
        });
        geometries.forEach(geometry => geometry.dispose());
        materials.forEach(material => material.dispose());
        textures.forEach(texture => texture.dispose());
    }

    configureShadowCamera() {
        if (!this.keyLight || !this.bounds) return;

        const centerX = (this.bounds.minX + this.bounds.maxX) / 2 - this.centerOffset.x;
        const centerZ = (this.bounds.minY + this.bounds.maxY) / 2 - this.centerOffset.y;
        const span = Math.max(this.bounds.width, this.bounds.height, 8);
        const extent = span * 0.7;
        const shadowCamera = this.keyLight.shadow.camera;

        this.keyLight.position.set(centerX + span, this.sceneHeight + span * 1.5, centerZ + span);
        this.keyLight.target.position.set(centerX, 0, centerZ);
        shadowCamera.left = -extent;
        shadowCamera.right = extent;
        shadowCamera.top = extent;
        shadowCamera.bottom = -extent;
        shadowCamera.far = span * 5;
        shadowCamera.updateProjectionMatrix();
    }

    clear() {
        this.animatingMeshes.length = 0;
        this.clearRoute();
        Object.values(this.groups).forEach(g => {
            while (g.children.length > 0) {
                const obj = g.children[0];
                this.disposeObjectResources(obj);
                g.remove(obj);
            }
        });
        this.floorGroups.forEach(floorGroup => {
            this.disposeObjectResources(floorGroup);
            if (floorGroup.parent) floorGroup.parent.remove(floorGroup);
        });
        this.floorGroups.clear();
        this.wallMaterial = null;
        this.selectableMeshes = [];
        this.selectedRoomMesh = null;
        this.selectedRoomOriginalColor = null;
    }

    createFloorGroups(sceneData) {
        const levels = new Set((sceneData.meta.levels || []).map(item => Number(item.floorIndex ?? item.level) || 0));
        ["rooms", "walls", "doors", "windows"].forEach(collection => {
            (sceneData[collection] || []).forEach(item => levels.add(this.getItemFloorIndex(item)));
        });
        if (!levels.size) levels.add(0);

        Array.from(levels).sort((a, b) => a - b).forEach(floorIndex => {
            const floorGroup = new THREE.Group();
            floorGroup.name = `floorGroup_${floorIndex}`;
            floorGroup.floorIndex = floorIndex;
            floorGroup.userData = { floorIndex, currentIsolationOpacity: 1 };
            floorGroup.position.y = this.getLevelElevation(floorIndex);
            this.floorLayerNames.forEach(layerName => {
                const layer = new THREE.Group();
                layer.name = layerName;
                layer.visible = this.layerVisibility[layerName];
                floorGroup.add(layer);
            });
            this.floorGroups.set(floorIndex, floorGroup);
            this.scene.add(floorGroup);
        });
    }

    getWallThickness() {
        return Math.max(0.05, Number(this.currentSceneData?.meta?.wallThickness) || 0.2);
    }

    getOpeningRotation(opening, floorIndex) {
        const center = opening.center || [0, 0];
        let bestDistance = Infinity;
        let rotation = 0;

        (this.currentSceneData?.walls || []).forEach(wall => {
            if (this.getItemFloorIndex(wall) !== floorIndex || !wall.polygon || wall.polygon.length < 3) return;
            const xs = wall.polygon.map(point => Number(point[0]));
            const ys = wall.polygon.map(point => Number(point[1]));
            const minX = Math.min(...xs), maxX = Math.max(...xs);
            const minY = Math.min(...ys), maxY = Math.max(...ys);
            const width = maxX - minX;
            const height = maxY - minY;
            if (Math.max(width, height) < Math.max(0.5, Math.min(width, height) * 2)) return;

            const isVertical = height > width;
            const alongDistance = isVertical
                ? Math.max(minY - center[1], 0, center[1] - maxY)
                : Math.max(minX - center[0], 0, center[0] - maxX);
            const acrossDistance = isVertical
                ? Math.abs(center[0] - (minX + maxX) / 2)
                : Math.abs(center[1] - (minY + maxY) / 2);
            const distance = Math.hypot(alongDistance, acrossDistance);
            if (distance < bestDistance) {
                bestDistance = distance;
                rotation = isVertical ? Math.PI / 2 : 0;
            }
        });

        return rotation;
    }

    getItemFloorIndex(item) {
        const value = item && (item.floorIndex ?? item.level);
        return Number.isFinite(Number(value)) ? Number(value) : 0;
    }

    getFloorLayer(floorIndex, layerName) {
        return this.floorGroups.get(Number(floorIndex))?.getObjectByName(layerName) || null;
    }

    createFloorInfoPanel() {
        const panel = document.createElement("div");
        panel.className = "floor-info-panel";
        panel.hidden = true;
        panel.setAttribute("role", "status");
        panel.setAttribute("aria-live", "polite");

        const heading = document.createElement("h3");
        heading.className = "floor-info-title";
        const details = document.createElement("div");
        details.className = "floor-info-details";
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "floor-info-close";
        closeButton.textContent = "Close";
        closeButton.addEventListener("click", () => this.restoreFloorIsolation());

        panel.append(heading, details, closeButton);
        this.container.appendChild(panel);
        this.floorInfoPanel = panel;
        this.floorInfoHeading = heading;
        this.floorInfoDetails = details;
    }

    getFloorStats(floorIndex) {
        const rooms = (this.currentSceneData?.rooms || []).filter(room => this.getItemFloorIndex(room) === floorIndex);
        const totalArea = rooms.reduce((sum, room) => {
            const polygon = room.polygon || [];
            if (polygon.length < 3) return sum;
            let twiceArea = 0;
            polygon.forEach((point, index) => {
                const next = polygon[(index + 1) % polygon.length];
                twiceArea += point[0] * next[1] - next[0] * point[1];
            });
            return sum + Math.abs(twiceArea) / 2;
        }, 0);
        const levelInfo = (this.currentSceneData?.meta?.levels || []).find(item => Number(item.floorIndex ?? item.level) === floorIndex);
        return {
            name: levelInfo?.name || `Level ${floorIndex + 1}`,
            roomCount: rooms.length,
            totalArea
        };
    }

    showFloorInfoPanel(floorIndex) {
        if (!this.floorInfoPanel) return;
        const stats = this.getFloorStats(floorIndex);
        this.floorInfoHeading.textContent = stats.name;
        this.floorInfoDetails.replaceChildren();
        [
            [`Rooms`, String(stats.roomCount)],
            [`Total area`, `${stats.totalArea.toFixed(1)} m²`]
        ].forEach(([label, value]) => {
            const row = document.createElement("p");
            const labelNode = document.createElement("span");
            const valueNode = document.createElement("strong");
            labelNode.textContent = label;
            valueNode.textContent = value;
            row.append(labelNode, valueNode);
            this.floorInfoDetails.appendChild(row);
        });
        this.floorInfoPanel.hidden = false;
        requestAnimationFrame(() => this.floorInfoPanel.classList.add("is-visible"));
    }

    hideFloorInfoPanel() {
        if (!this.floorInfoPanel) return;
        this.floorInfoPanel.classList.remove("is-visible");
        this.floorInfoPanel.hidden = true;
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

    getLevelElevation(level) {
        const numericLevel = Math.max(0, Number(level) || 0);
        const levelInfo = (this.currentSceneData?.meta?.levels || []).find(item =>
            Number(item.floorIndex ?? item.level) === numericLevel
        );
        const declaredElevation = Number(levelInfo?.elevation);
        return Number.isFinite(declaredElevation) ? declaredElevation : numericLevel * this.floorHeight;
    }

    updateVisibleLevels() {
        this.floorGroups.forEach((group, floorIndex) => {
            group.visible = this.visibleLevel === null || floorIndex === this.visibleLevel;
        });
        this.refreshSelectableMeshes();
    }

    setVisibleLevel(level) {
        if (this.currentIsolatedFloor !== null || this.isolationTween) this.restoreFloorIsolation();
        this.visibleLevel = level === null || level === "all" ? null : Number(level);
        this.updateVisibleLevels();
        if (this.currentSceneData) {
            if (this.is2DMode) this.setTopDownView();
            else this.setPerspectiveView();
        }
    }

    refreshSelectableMeshes() {
        this.selectableMeshes = [];
        this.floorGroups.forEach(floorGroup => {
            if (!floorGroup.visible) return;
            ["walls", "rooms"].forEach(layerName => {
                const layer = floorGroup.getObjectByName(layerName);
                if (!layer || !layer.visible) return;
                layer.traverse(object => {
                    if (object.isMesh && (object.userData.isWall || object.userData.isFloorSurface)) {
                        this.selectableMeshes.push(object);
                    }
                });
            });
        });
    }

    setFloorOpacity(floorGroup, opacity) {
        floorGroup.traverse(object => {
            if (!object.material) return;
            if (!object.userData.floorIsolationOriginalMaterial) {
                object.userData.floorIsolationOriginalMaterial = object.material;
                const originals = Array.isArray(object.material) ? object.material : [object.material];
                object.material = Array.isArray(object.material)
                    ? originals.map(material => material.clone())
                    : object.material.clone();
            }
            const materials = Array.isArray(object.material) ? object.material : [object.material];
            materials.forEach(material => {
                if (material.userData.floorIsolationOriginalTransparent === undefined) {
                    material.userData.floorIsolationOriginalTransparent = material.transparent;
                    material.userData.floorIsolationOriginalDepthWrite = material.depthWrite;
                }
                material.transparent = opacity < 0.999 || material.userData.floorIsolationOriginalTransparent;
                material.opacity = opacity;
                material.depthWrite = opacity >= 0.999
                    ? material.userData.floorIsolationOriginalDepthWrite
                    : false;
                material.needsUpdate = true;
            });
        });
        floorGroup.userData.currentIsolationOpacity = opacity;
    }

    restoreFloorMaterials(floorGroup) {
        floorGroup.traverse(object => {
            const original = object.userData.floorIsolationOriginalMaterial;
            if (!original) return;
            const temporary = Array.isArray(object.material) ? object.material : [object.material];
            temporary.forEach(material => material.dispose());
            object.material = original;
            delete object.userData.floorIsolationOriginalMaterial;
        });
        floorGroup.userData.currentIsolationOpacity = 1;
    }

    startFloorIsolationTween(targetFloorIndex) {
        const starts = new Map();
        this.floorGroups.forEach((group, floorIndex) => {
            starts.set(floorIndex, {
                y: group.position.y,
                opacity: targetFloorIndex === null
                    ? (Number(group.userData.currentIsolationOpacity) || 1)
                    : (floorIndex === targetFloorIndex ? 1 : 0.05)
            });
        });
        this.isolationTween = {
            targetFloorIndex,
            starts,
            startTime: performance.now(),
            duration: 650
        };
        if (targetFloorIndex === null) {
            this.currentIsolatedFloor = null;
            this.hideFloorInfoPanel();
        } else {
            this.currentIsolatedFloor = targetFloorIndex;
            this.showFloorInfoPanel(targetFloorIndex);
        }
        this.floorGroups.forEach((group, floorIndex) => {
            if (targetFloorIndex !== null) {
                // Hide other levels immediately; waiting for the first animation
                // frame lets their opaque walls and labels overlap the selected floor.
                this.setFloorOpacity(group, floorIndex === targetFloorIndex ? 1 : 0.05);
            }
            const labels = group.getObjectByName("labels");
            if (!labels) return;
            const shouldShowLabels = this.layerVisibility.labels
                && (targetFloorIndex === null || floorIndex === targetFloorIndex);
            labels.traverse(label => {
                if (label !== labels && label.userData.floorIndex !== undefined) {
                    label.userData.floorIsolationVisible = shouldShowLabels;
                    label.visible = shouldShowLabels;
                }
            });
        });
    }

    requestFloorIsolation(floorIndex) {
        if (!this.floorGroups.has(floorIndex)) return;

        if (this.currentIsolatedFloor !== null) {
            if (this.currentIsolatedFloor === floorIndex) {
                this.pendingFloorIsolation = null;
                this.startFloorIsolationTween(null);
                return;
            }
            this.pendingFloorIsolation = floorIndex;
            this.startFloorIsolationTween(null);
            return;
        }

        if (this.isolationTween) {
            // A reset is already in progress. Finish it before starting another floor.
            this.pendingFloorIsolation = floorIndex;
            return;
        }
        this.startFloorIsolationTween(floorIndex);
    }

    restoreFloorIsolation() {
        this.pendingFloorIsolation = null;
        if (this.currentIsolatedFloor !== null || this.isolationTween) {
            this.startFloorIsolationTween(null);
        } else {
            this.hideFloorInfoPanel();
        }
    }

    updateFloorIsolation(now) {
        if (!this.isolationTween) return;
        const tween = this.isolationTween;
        const t = Math.min(1, (now - tween.startTime) / tween.duration);
        const eased = 1 - Math.pow(1 - t, 3);

        this.floorGroups.forEach((group, floorIndex) => {
            const baseY = this.getLevelElevation(floorIndex);
            const start = tween.starts.get(floorIndex) || { y: baseY, opacity: 1 };
            const targetY = tween.targetFloorIndex === floorIndex
                ? baseY + this.wallHeight * 3
                : baseY;
            const targetOpacity = tween.targetFloorIndex !== null && floorIndex !== tween.targetFloorIndex ? 0.05 : 1;
            group.position.y = THREE.MathUtils.lerp(start.y, targetY, eased);
            this.setFloorOpacity(group, THREE.MathUtils.lerp(start.opacity, targetOpacity, eased));
        });

        if (t < 1) return;
        this.floorGroups.forEach((group, floorIndex) => {
            const baseY = this.getLevelElevation(floorIndex);
            group.position.y = tween.targetFloorIndex === floorIndex ? baseY + this.wallHeight * 3 : baseY;
            if (tween.targetFloorIndex === null) this.restoreFloorMaterials(group);
            else this.setFloorOpacity(group, floorIndex === tween.targetFloorIndex ? 1 : 0.05);
        });
        this.isolationTween = null;

        if (tween.targetFloorIndex === null) {
            const nextFloor = this.pendingFloorIsolation;
            this.pendingFloorIsolation = null;
            if (nextFloor !== null) this.startFloorIsolationTween(nextFloor);
        }
    }

    buildGroundAndGrid() {
        const span = Math.max(this.bounds.width, this.bounds.height, 20);
        const gridSize = Math.ceil(span * 1.8);
        const divisions = gridSize; // 1 division = exactly 1 meter!

        // 1-meter architectural grid helper
        const grid = new THREE.GridHelper(gridSize, divisions, 0xd02020, 0x121212);
        grid.position.y = -0.01;
        this.groups.grid.add(grid);

        // Ground foundation plane
        const groundGeo = new THREE.PlaneGeometry(gridSize * 1.5, gridSize * 1.5);
        const groundMat = new THREE.MeshStandardMaterial({
            color: 0xf0f0f0,
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
        const wallMat = this.wallMaterial || (this.wallMaterial = new THREE.MeshStandardMaterial({
            color: 0xf0f0f0,      // Architectural paper-white plaster
            roughness: 0.8,
            metalness: 0.1,
            side: THREE.DoubleSide
        }));

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
            const level = this.getItemFloorIndex(wall);
            wallMesh.position.y = 0;
            wallMesh.scale.set(1, 0.001, 1);
            wallMesh.castShadow = true;
            wallMesh.receiveShadow = true;
            wallMesh.userData = { isWall: true, wallId: wall.id, level, floorIndex: level };

            this.getFloorLayer(level, "walls")?.add(wallMesh);
            this.animatingMeshes.push(wallMesh);
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

            for (let i = 1; i < poly.length; i++) {
                const pt = this.toWorldCoords(poly[i][0], poly[i][1]);
                shape.lineTo(pt.x, -pt.z);
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
                transparent: true,
                opacity: 0,
                depthWrite: false,
                side: THREE.DoubleSide
            });

            const roomMesh = new THREE.Mesh(roomGeo, roomMat);
            const level = this.getItemFloorIndex(room);
            roomMesh.position.y = 0.02; // Floor group supplies the level elevation.
            roomMesh.scale.set(1, 0.001, 1);
            roomMesh.castShadow = true;
            roomMesh.receiveShadow = true;
            roomMesh.userData = {
                isRoom: true,
                level,
                floorIndex: level,
                isFloorSurface: true,
                roomData: room,
                originalColor: colorHex
            };

            this.getFloorLayer(level, "rooms")?.add(roomMesh);
            this.animatingMeshes.push(roomMesh);

            // Calculate centroid for floating label badge
            const [centroidPlanX, centroidPlanY] = this.getPolygonCentroid(poly);
            const centroid = this.toWorldCoords(centroidPlanX, centroidPlanY);

            // Create floating 3D text badge
            const badgeSprite = this.createRoomBadgeSprite(room);
            badgeSprite.position.set(centroid.x, 1.4, centroid.z);
            badgeSprite.userData.level = level;
            badgeSprite.userData.floorIndex = level;
            badgeSprite.userData.confidence = Number(room.confidence) || 0;
            badgeSprite.userData.floorIsolationVisible = true;
            badgeSprite.userData.baseLabelOpacity = 1;
            badgeSprite.userData.buildRevealProgress = 0;
            badgeSprite.material.opacity = 0;
            roomMesh.userData.buildRevealLabel = badgeSprite;
            this.getFloorLayer(level, "labels")?.add(badgeSprite);
        });
    }

    getPolygonCentroid(polygon) {
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
        if (Math.abs(twiceArea) > 1e-8) return [xSum / (3 * twiceArea), ySum / (3 * twiceArea)];
        return polygon.reduce((sum, point) => [
            sum[0] + point[0] / polygon.length,
            sum[1] + point[1] / polygon.length
        ], [0, 0]);
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

        // Square paper badge, with a heavy ink border and a primary-color room marker.
        const x = 32, y = 32, w = 448, h = 192;
        ctx.fillStyle = "#F0F0F0";
        ctx.beginPath();
        ctx.rect(x, y, w, h);
        ctx.closePath();
        ctx.fill();

        // Color border matching room type
        const typeColorHex = this.roomColors[room.type] || 0x1040c0;
        const hexStr = "#" + typeColorHex.toString(16).padStart(6, "0");
        ctx.strokeStyle = "#121212";
        ctx.lineWidth = 8;
        ctx.stroke();

        // Type color accent pill
        ctx.fillStyle = hexStr;
        ctx.beginPath();
        ctx.rect(56, 52, 12, 40);
        ctx.fill();

        // Main Room Label Text
        ctx.fillStyle = "#121212";
        ctx.font = "900 36px 'Outfit', sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(room.label || `Room ${room.id}`, 80, 84);

        // Subtitle: Room Type and Confidence
        ctx.fillStyle = "#121212";
        ctx.font = "500 24px 'Outfit', sans-serif";
        const typeCapitalized = (room.type || "room").toUpperCase();
        const confidence = Number(room.confidence);
        const confidenceText = Number.isFinite(confidence) && confidence > 0
            ? `${Math.round(confidence * 100)}% Conf`
            : "Unclassified";
        ctx.fillText(`${typeCapitalized} • ${confidenceText}`, 80, 140);

        // Badge sprite texture
        const texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;
        texture.generateMipmaps = false;

        const spriteMat = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            depthTest: false, // Always visible above walls
            depthWrite: false
        });

        const sprite = new THREE.Sprite(spriteMat);
        sprite.scale.set(3.2, 1.6, 1.0);
        return sprite;
    }

    /**
     * Builds 3D door openings and subtle swinging door panels.
     */
    buildDoors(doors) {
        const wallMat = this.wallMaterial || new THREE.MeshStandardMaterial({
            color: 0xf0f0f0,
            roughness: 0.8,
            metalness: 0.1,
            side: THREE.DoubleSide
        });
        this.wallMaterial = wallMat;
        const doorPanelMat = new THREE.MeshStandardMaterial({ color: 0xd02020, roughness: 0.8, metalness: 0 });

        doors.forEach(door => {
            const center = door.center || [0, 0];
            const pt = this.toWorldCoords(center[0], center[1]);
            const width = Math.max(0.6, door.width || 0.9);
            const doorHeight = 2.1; // Standard door height in meters
            const wallThickness = this.getWallThickness();

            // Door frame group
            const doorGroup = new THREE.Group();
            const level = this.getItemFloorIndex(door);
            doorGroup.position.set(pt.x, 0, pt.z);
            doorGroup.rotation.y = this.getOpeningRotation(door, level);
            doorGroup.userData.level = level;
            doorGroup.userData.floorIndex = level;

            const headerHeight = Math.max(0, this.wallHeight - doorHeight);
            if (headerHeight > 0) {
                const header = new THREE.Mesh(
                    new THREE.BoxGeometry(width, headerHeight, wallThickness),
                    wallMat
                );
                header.position.y = doorHeight + headerHeight / 2;
                header.castShadow = true;
                header.receiveShadow = true;
                header.scale.set(1, 0.001, 1);
                header.userData = { isWall: true, floorIndex: level, level, openingFiller: "door-header" };
                doorGroup.add(header);
                this.animatingMeshes.push(header);
            }

            // A thin wooden leaf, rotated open around its approximate hinge side.
            const panelGeo = new THREE.BoxGeometry(width * 0.95, doorHeight, 0.05);
            const panelMesh = new THREE.Mesh(panelGeo, doorPanelMat);
            panelMesh.position.set(width * 0.25, doorHeight / 2, 0);
            panelMesh.rotation.y = Math.PI / 4; // 45-degree welcoming open swing
            panelMesh.castShadow = true;
            doorGroup.add(panelMesh);

            this.getFloorLayer(level, "doors")?.add(doorGroup);
        });
    }

    /**
     * Builds translucent glass windows and architectural window frames.
     */
    buildWindows(windows) {
        const wallMat = this.wallMaterial || new THREE.MeshStandardMaterial({
            color: 0xf0f0f0,
            roughness: 0.8,
            metalness: 0.1,
            side: THREE.DoubleSide
        });
        this.wallMaterial = wallMat;
        const glassMat = new THREE.MeshStandardMaterial({
            color: 0x1040c0,
            transparent: true,
            opacity: 0.4,
            depthWrite: false
        });

        windows.forEach(win => {
            const center = win.center || [0, 0];
            const pt = this.toWorldCoords(center[0], center[1]);
            const width = Math.max(0.8, win.width || 1.2);
            const sillHeight = 0.9;
            const windowTop = 1.5;
            const winHeight = windowTop - sillHeight;
            const wallThickness = this.getWallThickness();

            const winGroup = new THREE.Group();
            const level = this.getItemFloorIndex(win);
            winGroup.position.set(pt.x, 0, pt.z);
            winGroup.rotation.y = this.getOpeningRotation(win, level);
            winGroup.userData.level = level;
            winGroup.userData.floorIndex = level;

            // Glass pane fills the 0.9m to 1.5m opening and protrudes slightly past the wall.
            const paneDepth = wallThickness + 0.05;
            const glassGeo = new THREE.BoxGeometry(width, winHeight, paneDepth);
            const glassMesh = new THREE.Mesh(glassGeo, glassMat);
            glassMesh.position.y = (sillHeight + windowTop) / 2;
            winGroup.add(glassMesh);

            // The white sill and header meet the pane exactly and match wall thickness.
            const sillWall = new THREE.Mesh(
                new THREE.BoxGeometry(width, sillHeight, wallThickness),
                wallMat
            );
            sillWall.position.y = sillHeight / 2;
            sillWall.castShadow = true;
            sillWall.receiveShadow = true;
            sillWall.scale.set(1, 0.001, 1);
            sillWall.userData = { isWall: true, floorIndex: level, level, windowFiller: "sill" };
            winGroup.add(sillWall);
            this.animatingMeshes.push(sillWall);

            const headerHeight = Math.max(0, this.wallHeight - windowTop);
            if (headerHeight > 0) {
                const header = new THREE.Mesh(
                    new THREE.BoxGeometry(width, headerHeight, wallThickness),
                    wallMat
                );
                header.position.y = windowTop + headerHeight / 2;
                header.castShadow = true;
                header.receiveShadow = true;
                header.scale.set(1, 0.001, 1);
                header.userData = { isWall: true, floorIndex: level, level, windowFiller: "header" };
                winGroup.add(header);
                this.animatingMeshes.push(header);
            }

            this.getFloorLayer(level, "windows")?.add(winGroup);
        });
    }

    clearOpeningLayer(layerName) {
        const staleMaterials = new Set();
        this.floorGroups.forEach(group => {
            const layer = group.getObjectByName(layerName);
            if (!layer) return;
            const oldChildren = new Set(layer.children);
            this.animatingMeshes = this.animatingMeshes.filter(mesh => {
                let ancestor = mesh;
                while (ancestor && ancestor.parent !== layer) ancestor = ancestor.parent;
                return !(ancestor && oldChildren.has(ancestor));
            });
            layer.traverse(object => {
                if (object.geometry) object.geometry.dispose();
                if (!object.material) return;
                const materials = Array.isArray(object.material) ? object.material : [object.material];
                materials.forEach(material => {
                    if (material !== this.wallMaterial) staleMaterials.add(material);
                });
            });
            layer.clear();
        });
        staleMaterials.forEach(material => material.dispose());
    }

    /**
     * Interactively updates wall height across all walls.
     */
    setWallHeight(heightMeters) {
        if (!this.currentSceneData) return;
        this.wallHeight = Math.max(0.2, parseFloat(heightMeters) || 3.0);
        const floorIndices = Array.from(this.floorGroups.keys());
        const highestFloor = floorIndices.length
            ? Math.max(...floorIndices.map(index => this.getLevelElevation(index)))
            : 0;
        this.sceneHeight = highestFloor + this.wallHeight;
        this.floorGroups.forEach((group, floorIndex) => {
            group.position.y = this.getLevelElevation(floorIndex);
        });
        
        // Rebuild only the walls layer
        this.floorGroups.forEach(group => {
            const wallLayer = group.getObjectByName("walls");
            while (wallLayer.children.length > 0) {
                const obj = wallLayer.children[0];
                if (obj.geometry) obj.geometry.dispose();
                wallLayer.remove(obj);
            }
        });
        this.buildWalls(this.currentSceneData.walls || []);
        this.clearOpeningLayer("doors");
        this.clearOpeningLayer("windows");
        this.buildDoors(this.currentSceneData.doors || []);
        this.buildWindows(this.currentSceneData.windows || []);
        this.configureShadowCamera();
        this.updateVisibleLevels();
        this.refreshSelectableMeshes();
    }

    /**
     * Raycasting click handler: highlights selected room and notifies UI.
     */
    onPointerClick(event) {
        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.selectableMeshes, false);

        if (!intersects.length) {
            this.restoreFloorIsolation();
            return;
        }

        const hitObject = intersects[0].object;
        let floorGroup = hitObject;
        while (floorGroup && !(floorGroup.isGroup
            && floorGroup.name.startsWith("floorGroup_")
            && Number.isFinite(Number(floorGroup.userData.floorIndex)))) {
            floorGroup = floorGroup.parent;
        }
        if (!floorGroup) {
            this.restoreFloorIsolation();
            return;
        }
        if (hitObject.userData.isFloorSurface) this.selectRoom(hitObject);
        this.requestFloorIsolation(Number(floorGroup.userData.floorIndex));
    }

    selectRoom(roomMesh) {
        // Reset previously selected room color
        if (this.selectedRoomMesh && this.selectedRoomOriginalColor !== null) {
            this.selectedRoomMesh.material.color.setHex(this.selectedRoomOriginalColor);
            this.selectedRoomMesh.material.emissive.setHex(0x000000);
        }

        this.selectedRoomMesh = roomMesh;
        this.selectedRoomOriginalColor = roomMesh.userData.originalColor;

        // Highlight with the Bauhaus yellow selection color.
        roomMesh.material.color.setHex(0xf0c020);
        roomMesh.material.emissive.setHex(0xf0c020);

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
        this.isEyeLevelView = false;
        const width = Math.max(this.bounds ? this.bounds.width : 16, 1);
        const depth = Math.max(this.bounds ? this.bounds.height : 12, 1);
        const selectedElevation = this.visibleLevel === null ? 0 : this.getLevelElevation(this.visibleLevel);
        const height = Math.max(this.visibleLevel === null ? this.sceneHeight : this.wallHeight, 1);
        const verticalFov = THREE.MathUtils.degToRad(this.camera.fov);
        const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * this.camera.aspect);
        const viewDirection = new THREE.Vector3(1, 0.85, 1).normalize();
        const right = new THREE.Vector3().crossVectors(viewDirection, new THREE.Vector3(0, 1, 0)).normalize();
        const cameraUp = new THREE.Vector3().crossVectors(right, viewDirection).normalize();

        // Aim at the floor-plan center so the footprint is centered in the viewport.
        // Fit every corner of the plan and wall volume to avoid clipping on short screens.
        const target = new THREE.Vector3(0, selectedElevation + height * 0.15, 0);
        const halfWidth = width / 2;
        const halfDepth = depth / 2;
        const tanHorizontal = Math.tan(horizontalFov / 2);
        const tanVertical = Math.tan(verticalFov / 2);
        let distance = 0;

        [-halfWidth, halfWidth].forEach(x => {
            [-halfDepth, halfDepth].forEach(z => {
                [selectedElevation, selectedElevation + height].forEach(y => {
                    const offset = new THREE.Vector3(x, y, z).sub(target);
                    const towardCamera = offset.dot(viewDirection);
                    const horizontalExtent = Math.abs(offset.dot(right));
                    const verticalExtent = Math.abs(offset.dot(cameraUp));
                    distance = Math.max(
                        distance,
                        towardCamera + horizontalExtent / tanHorizontal,
                        towardCamera + verticalExtent / tanVertical
                    );
                });
            });
        });
        distance *= 1.25;

        this.controls.target.copy(target);
        this.camera.position.copy(target).addScaledVector(viewDirection, distance);
        this.camera.far = Math.max(1000, distance * 10);
        this.camera.updateProjectionMatrix();
        this.controls.maxDistance = Math.max(150, distance * 4);
        this.controls.maxPolarAngle = Math.PI / 2 + 0.05;
        this.controls.update();
    }

    setTopDownView() {
        this.is2DMode = true;
        this.isEyeLevelView = false;
        const span = Math.max(this.bounds ? this.bounds.width : 20, this.bounds ? this.bounds.height : 20, 20);
        const targetY = this.visibleLevel === null ? 0 : this.getLevelElevation(this.visibleLevel);
        this.controls.target.set(0, targetY, 0);
        this.camera.position.set(0, targetY + span * 1.6, 0.01); // Look straight down
        this.controls.update();
    }

    setEyeLevelView() {
        this.is2DMode = false;
        this.isEyeLevelView = true;

        const rooms = this.currentSceneData?.rooms || [];
        const getArea = room => {
            const polygon = room.polygon || [];
            if (polygon.length < 3) return 0;
            let twiceArea = 0;
            polygon.forEach((point, index) => {
                const next = polygon[(index + 1) % polygon.length];
                twiceArea += point[0] * next[1] - next[0] * point[1];
            });
            return Math.abs(twiceArea) / 2;
        };
        const availableRooms = this.visibleLevel === null
            ? rooms
            : rooms.filter(room => this.getItemFloorIndex(room) === this.visibleLevel);
        const preferredRooms = availableRooms.filter(room => ["corridor", "entrance"].includes(
            String(room.type || "").toLowerCase()
        ));
        const room = (preferredRooms.length ? preferredRooms : availableRooms)
            .slice()
            .sort((a, b) => getArea(b) - getArea(a))[0]
            || rooms.slice().sort((a, b) => getArea(b) - getArea(a))[0];

        let worldX = 0;
        let worldZ = 0;
        let floorIndex = this.visibleLevel === null ? 0 : this.visibleLevel;
        if (room?.polygon?.length) {
            floorIndex = this.getItemFloorIndex(room);
            let twiceArea = 0;
            let centroidX = 0;
            let centroidY = 0;
            room.polygon.forEach((point, index) => {
                const next = room.polygon[(index + 1) % room.polygon.length];
                const cross = point[0] * next[1] - next[0] * point[1];
                twiceArea += cross;
                centroidX += (point[0] + next[0]) * cross;
                centroidY += (point[1] + next[1]) * cross;
            });
            if (Math.abs(twiceArea) > 1e-8) {
                centroidX /= 3 * twiceArea;
                centroidY /= 3 * twiceArea;
            } else {
                centroidX = room.polygon.reduce((sum, point) => sum + point[0], 0) / room.polygon.length;
                centroidY = room.polygon.reduce((sum, point) => sum + point[1], 0) / room.polygon.length;
            }
            const world = this.toWorldCoords(centroidX, centroidY);
            worldX = world.x;
            worldZ = world.z;
        }

        const floorElevation = this.getLevelElevation(floorIndex);
        const eyeY = floorElevation + 1.7;
        const span = Math.max(this.bounds?.width || 20, this.bounds?.height || 20, 20);
        this.camera.near = 0.05;
        this.camera.far = Math.max(1000, this.sceneHeight + span * 10);
        this.camera.updateProjectionMatrix();
        this.controls.target.set(worldX, eyeY - 0.12, worldZ - 2);
        this.camera.position.set(worldX, eyeY, worldZ);
        this.controls.minDistance = 0.1;
        this.controls.maxDistance = Math.max(150, span * 8);
        this.controls.update();
        this.updateRoomLabelVisibility(1 / 60);
    }

    focusRoom(room) {
        const polygon = room && room.polygon;
        if (!polygon || polygon.length < 3) return;
        const centroid = polygon.reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0])
            .map(value => value / polygon.length);
        const world = this.toWorldCoords(centroid[0], centroid[1]);
        const targetStart = this.controls.target.clone();
        const targetEnd = new THREE.Vector3(world.x, this.getLevelElevation(this.getItemFloorIndex(room)), world.z);
        const span = Math.max(5, Math.min(this.bounds.width, this.bounds.height, 10));
        const cameraStart = this.camera.position.clone();
        const cameraEnd = new THREE.Vector3(world.x + span * 0.9, targetEnd.y + span * 0.9, world.z + span * 0.9);
        const startTime = performance.now();
        const duration = 700;

        const animateFocus = (now) => {
            const t = Math.min(1, (now - startTime) / duration);
            const eased = 1 - Math.pow(1 - t, 3);
            this.camera.position.lerpVectors(cameraStart, cameraEnd, eased);
            this.controls.target.lerpVectors(targetStart, targetEnd, eased);
            this.controls.update();
            if (t < 1) requestAnimationFrame(animateFocus);
        };
        requestAnimationFrame(animateFocus);
    }

    drawRoute(planCoordinates, level = 0) {
        this.clearRoute();
        const group = this.groups.route;
        if (!planCoordinates || planCoordinates.length < 3) return;

        const pathNodes = planCoordinates.map(node => {
            const point = Array.isArray(node) ? node : (node.point || [node.x, node.y]);
            const floorIndex = Array.isArray(node) ? Number(level) || 0 : Number(node.floorIndex ?? level) || 0;
            const world = this.toWorldCoords(point[0], point[1]);
            return {
                floorIndex,
                position: new THREE.Vector3(world.x, this.getLevelElevation(floorIndex) + 0.1, world.z)
            };
        }).filter((node, index, nodes) => {
            if (index === 0) return true;
            const previous = nodes[index - 1];
            return node.floorIndex !== previous.floorIndex
                || node.position.distanceToSquared(previous.position) > 1e-8;
        });
        if (pathNodes.length < 3) return;

        // Keep each floor segment smooth, but make every level change a truly
        // vertical LineCurve3 segment between the two stacked stair/elevator nodes.
        const curvePath = new THREE.CurvePath();
        let horizontalRun = [pathNodes[0].position];
        const flushHorizontalRun = () => {
            if (horizontalRun.length >= 3) {
                curvePath.add(new THREE.CatmullRomCurve3(horizontalRun, false, "centripetal"));
            } else if (horizontalRun.length === 2) {
                curvePath.add(new THREE.LineCurve3(horizontalRun[0], horizontalRun[1]));
            }
        };
        for (let index = 1; index < pathNodes.length; index++) {
            const previous = pathNodes[index - 1];
            const current = pathNodes[index];
            if (current.floorIndex !== previous.floorIndex) {
                flushHorizontalRun();
                curvePath.add(new THREE.LineCurve3(previous.position, current.position));
                horizontalRun = [current.position];
            } else {
                horizontalRun.push(current.position);
            }
        }
        flushHorizontalRun();
        const geometry = new THREE.TubeGeometry(curvePath, Math.max(64, pathNodes.length * 32), 0.15, 10, false);
        const textureCanvas = document.createElement("canvas");
        textureCanvas.width = 128;
        textureCanvas.height = 32;
        const ctx = textureCanvas.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, textureCanvas.width, textureCanvas.height);
        ctx.fillStyle = "#121212";
        for (let x = -32; x < textureCanvas.width + 32; x += 32) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x + 16, 0);
            ctx.lineTo(x + 32, textureCanvas.height);
            ctx.lineTo(x + 16, textureCanvas.height);
            ctx.closePath();
            ctx.fill();
        }
        const flowTexture = new THREE.CanvasTexture(textureCanvas);
        flowTexture.wrapS = THREE.RepeatWrapping;
        flowTexture.wrapT = THREE.RepeatWrapping;
        flowTexture.repeat.set(5, 1);
        const material = new THREE.MeshStandardMaterial({
            color: 0xf0c020,
            map: flowTexture,
            emissive: 0xf0c020,
            emissiveIntensity: 0.35,
            roughness: 0.8,
            metalness: 0
        });
        const route = new THREE.Mesh(geometry, material);
        route.castShadow = true;
        route.userData.level = Number(level) || 0;
        route.userData.floorIndex = Number(level) || 0;
        group.add(route);
        this.activeRouteTexture = flowTexture;
    }

    clearRoute() {
        const routeGroup = this.groups.route;
        while (routeGroup.children.length) {
            const route = routeGroup.children[0];
            this.scene.remove(route);
            if (route.parent) route.parent.remove(route);
            if (route.geometry) route.geometry.dispose();
            if (route.material) {
                const materials = Array.isArray(route.material) ? route.material : [route.material];
                materials.forEach(material => {
                    if (material.map) material.map.dispose();
                    material.dispose();
                });
            }
        }
        this.activeRouteTexture = null;
    }

    resetCameraView() {
        this.setPerspectiveView();
    }

    panWithArrowKeys(event) {
        if (!this.camera || !this.controls || event.altKey || event.ctrlKey || event.metaKey) return;
        if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;

        const target = event.target;
        const tagName = target && target.tagName ? target.tagName.toLowerCase() : "";
        if (tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable) return;

        event.preventDefault();

        // Pan parallel to the floor so arrow keys move across the plan instead of orbiting it.
        const forward = new THREE.Vector3(
            this.controls.target.x - this.camera.position.x,
            0,
            this.controls.target.z - this.camera.position.z
        ).normalize();
        const right = new THREE.Vector3(-forward.z, 0, forward.x);
        const planSpan = Math.max(this.bounds ? this.bounds.width : 12, this.bounds ? this.bounds.height : 12);
        const step = Math.max(0.25, Math.min(planSpan * 0.04, 3)) * (event.shiftKey ? 3 : 1);
        const movement = new THREE.Vector3();

        if (event.key === "ArrowUp") movement.copy(forward);
        if (event.key === "ArrowDown") movement.copy(forward).negate();
        if (event.key === "ArrowRight") movement.copy(right);
        if (event.key === "ArrowLeft") movement.copy(right).negate();

        movement.multiplyScalar(step);
        this.camera.position.add(movement);
        this.controls.target.add(movement);
        this.controls.update();
    }

    /**
     * Layer Visibility Toggles
     */
    toggleLayer(layerName, isVisible) {
        this.layerVisibility[layerName] = isVisible;
        if (this.groups[layerName]) {
            this.groups[layerName].visible = isVisible;
        }
        this.floorGroups.forEach(group => {
            const layer = group.getObjectByName(layerName);
            if (layer) layer.visible = isVisible;
        });
        this.refreshSelectableMeshes();
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
        this.floorGroups.forEach(floorGroup => {
            ["walls", "rooms", "doors", "windows"].forEach(layerName => {
                floorGroup.getObjectByName(layerName).children.forEach(child => {
                    if (child.isMesh || child.isGroup) exportScene.add(child.clone(true));
                });
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
                    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
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
        if (width <= 0 || height <= 0) return;
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    }

    updateRoomLabelVisibility(deltaSeconds) {
        if (!this.camera || !this.renderer) return;
        const rect = this.renderer.domElement.getBoundingClientRect();
        const viewportWidth = rect.width;
        const viewportHeight = rect.height;
        if (!viewportWidth || !viewportHeight) return;

        const candidates = [];
        const cameraPosition = this.camera.position;
        const tempWorldPosition = new THREE.Vector3();
        const verticalFov = THREE.MathUtils.degToRad(this.camera.fov || 50);
        const tanHalfFov = Math.tan(verticalFov / 2);
        const fadeStart = 16;
        const fadeEnd = 48;

        this.floorGroups.forEach(floorGroup => {
            const labelLayer = floorGroup.getObjectByName("labels");
            if (!labelLayer) return;
            labelLayer.children.forEach(sprite => {
                if (!sprite.isSprite || !sprite.material) return;
                const floorAllowed = floorGroup.visible
                    && labelLayer.visible
                    && sprite.userData.floorIsolationVisible !== false;
                sprite.getWorldPosition(tempWorldPosition);

                const distance = cameraPosition.distanceTo(tempWorldPosition);
                let distanceAlpha = 1;
                if (distance > fadeStart) {
                    const t = THREE.MathUtils.clamp((distance - fadeStart) / (fadeEnd - fadeStart), 0, 1);
                    distanceAlpha = 1 - t * t * (3 - 2 * t);
                }

                const cameraSpace = tempWorldPosition.clone().applyMatrix4(this.camera.matrixWorldInverse);
                const viewDepth = Math.max(0.01, -cameraSpace.z);
                const projected = tempWorldPosition.clone().project(this.camera);
                const inFrame = Math.abs(projected.x) <= 1.15 && Math.abs(projected.y) <= 1.15 && viewDepth > 0;
                const pixelScale = viewportHeight / (2 * tanHalfFov * viewDepth);
                const width = Math.max(18, sprite.scale.x * pixelScale);
                const height = Math.max(14, sprite.scale.y * pixelScale);
                const centerX = (projected.x + 1) * 0.5 * viewportWidth;
                const centerY = (1 - projected.y) * 0.5 * viewportHeight;
                const alpha = this.isEyeLevelView || !floorAllowed || !inFrame ? 0 : distanceAlpha;
                const baseOpacity = (sprite.userData.baseLabelOpacity ?? 1)
                    * (sprite.userData.buildRevealProgress ?? 1);
                const currentOpacity = Number(sprite.material.opacity ?? 1);
                const blend = Math.min(1, Math.max(0.01, deltaSeconds * 10));
                sprite.material.opacity = THREE.MathUtils.lerp(currentOpacity, baseOpacity * alpha, blend);
                sprite.visible = !this.isEyeLevelView && floorAllowed && inFrame;

                if (sprite.visible && alpha > 0.02) {
                    candidates.push({
                        sprite,
                        rect: {
                            left: centerX - width / 2,
                            right: centerX + width / 2,
                            top: centerY - height / 2,
                            bottom: centerY + height / 2
                        },
                        confidence: Number(sprite.userData.confidence) || 0,
                        distance
                    });
                }
            });
        });

        // Keep higher-confidence labels first, then prefer the closer badge on ties.
        candidates.sort((a, b) => b.confidence - a.confidence || a.distance - b.distance);
        const accepted = [];
        candidates.forEach(candidate => {
            const overlaps = accepted.some(other => candidate.rect.left < other.rect.right
                && candidate.rect.right > other.rect.left
                && candidate.rect.top < other.rect.bottom
                && candidate.rect.bottom > other.rect.top);
            if (overlaps) {
                candidate.sprite.visible = false;
                candidate.sprite.material.opacity = 0;
            } else {
                accepted.push(candidate);
            }
        });
    }

    updateBuildAnimations() {
        for (let index = this.animatingMeshes.length - 1; index >= 0; index--) {
            const mesh = this.animatingMeshes[index];
            mesh.scale.y = THREE.MathUtils.lerp(mesh.scale.y, 1.0, 0.05);
            if (mesh.userData.isFloorSurface && mesh.material) {
                mesh.material.opacity = THREE.MathUtils.lerp(mesh.material.opacity, 1.0, 0.05);
            }
            if (mesh.scale.y < 0.99) continue;

            mesh.scale.y = 1.0;
            if (mesh.userData.isFloorSurface && mesh.material) {
                mesh.material.opacity = 1;
                mesh.material.transparent = false;
                mesh.material.depthWrite = true;
                mesh.material.needsUpdate = true;
            }
            if (mesh.userData.buildRevealLabel) {
                mesh.userData.buildRevealLabel.userData.buildRevealProgress = 1;
            }
            this.animatingMeshes.splice(index, 1);
        }
    }

    animate() {
        requestAnimationFrame(now => {
            this.updateBuildAnimations();
            this.updateFloorIsolation(now);
            this.animate();
        });
        if (this.controls) this.controls.update();
        this.camera?.updateMatrixWorld();
        const now = performance.now();
        const deltaSeconds = this.lastLabelUpdateTime ? (now - this.lastLabelUpdateTime) / 1000 : 1 / 60;
        this.lastLabelUpdateTime = now;
        this.updateRoomLabelVisibility(deltaSeconds);
        if (this.activeRouteTexture) {
            this.activeRouteTexture.offset.x = (this.activeRouteTexture.offset.x - 0.006) % 1;
        }
        if (this.loadingGroup && this.loadingLaser) {
            this.loadingLaser.position.z = Math.sin(Date.now() * 0.002) * 10;
        }
        if (this.renderer && this.scene && this.camera) {
            this.renderer.render(this.scene, this.camera);
        }
    }
}
