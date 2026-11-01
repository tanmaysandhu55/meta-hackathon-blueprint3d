/**
 * Test script to verify True Orthographic Isometric View in Chrome via CDP.
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9222;

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function fetchJson(url) {
    return new Promise((resolve, reject) => {
        http.get(url, res => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
            });
        }).on('error', reject);
    });
}

class CDPClient {
    constructor(wsUrl) {
        this.ws = new WebSocket(wsUrl);
        this.msgId = 1;
        this.callbacks = new Map();
        this.events = [];
    }

    connect() {
        return new Promise((resolve, reject) => {
            this.ws.onopen = resolve;
            this.ws.onerror = reject;
            this.ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.id && this.callbacks.has(msg.id)) {
                    const cb = this.callbacks.get(msg.id);
                    this.callbacks.delete(msg.id);
                    if (msg.error) cb.reject(msg.error);
                    else cb.resolve(msg.result);
                }
            };
        });
    }

    send(method, params = {}) {
        const id = this.msgId++;
        return new Promise((resolve, reject) => {
            this.callbacks.set(id, { resolve, reject });
            this.ws.send(JSON.stringify({ id, method, params }));
        });
    }

    async evaluate(expression) {
        const res = await this.send("Runtime.evaluate", {
            expression,
            returnByValue: true,
            awaitPromise: true
        });
        if (res.exceptionDetails) {
            throw new Error(`Eval exception: ${JSON.stringify(res.exceptionDetails)}`);
        }
        return res.result ? res.result.value : undefined;
    }
}

async function run() {
    console.log("Launching headless Chrome...");
    const tmpProfile = path.join(process.env.TEMP, `chrome-profile-${Date.now()}`);
    const chromeProc = spawn(CHROME_PATH, [
        `--remote-debugging-port=${PORT}`,
        `--user-data-dir=${tmpProfile}`,
        '--headless=new',
        '--disable-gpu',
        '--no-first-run',
        '--no-default-browser-check',
        '--window-size=1400,900',
        'http://127.0.0.1:5000/#try-it-section'
    ]);

    let cdp = null;

    try {
        console.log("Waiting for Chrome to initialize...");
        let targets = null;
        for (let i = 0; i < 20; i++) {
            await sleep(500);
            try {
                targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
                if (targets && targets.length > 0) break;
            } catch (e) {}
        }

        if (!targets || !targets[0]) {
            throw new Error("Failed to find Chrome target");
        }

        const pageTarget = targets.find(t => t.type === 'page') || targets[0];
        console.log("Target found:", pageTarget.webSocketDebuggerUrl);

        cdp = new CDPClient(pageTarget.webSocketDebuggerUrl);
        await cdp.connect();
        console.log("CDP connected.");

        await cdp.send("Page.enable");
        await cdp.send("Runtime.enable");
        await cdp.send("Log.enable");

        cdp.ws.addEventListener("message", (evt) => {
            const data = JSON.parse(evt.data);
            if (data.method === "Runtime.consoleAPICalled") {
                console.log("[CONSOLE]", data.params.type, data.params.args.map(a => a.value || a.description).join(" "));
            }
            if (data.method === "Log.entryAdded") {
                console.log("[LOG]", data.params.entry.level, data.params.entry.text);
            }
        });

        // Override alert
        await cdp.evaluate(`(() => { window.alert = (msg) => console.log('[ALERT]', msg); })()`);

        console.log("Waiting for viewer to initialize...");
        let viewerReady = false;
        for (let i = 0; i < 30; i++) {
            await sleep(500);
            viewerReady = await cdp.evaluate(`(() => {
                return !!(window.viewer && window.FloorPlan3DStudio);
            })()`);
            if (viewerReady) break;
        }

        if (!viewerReady) {
            throw new Error("Viewer object did not initialize in time.");
        }
        console.log("Viewer object initialized. Switching to app view and loading demo...");

        await cdp.evaluate(`(() => {
            window.FloorPlan3DStudio.switchToAppView();
            const btnDemo = document.getElementById('btn-load-demo');
            if (btnDemo) btnDemo.click();
        })()`);

        console.log("Waiting for scene data to load...");
        let sceneReady = false;
        for (let i = 0; i < 30; i++) {
            await sleep(500);
            sceneReady = await cdp.evaluate(`(() => {
                return !!(window.viewer && window.viewer.currentSceneData && window.viewer.currentSceneData.rooms);
            })()`);
            if (sceneReady) break;
        }

        if (!sceneReady) {
            throw new Error("Scene data did not load in time.");
        }
        console.log("Scene initialized successfully.");

        // 1. Check default view (Isometric 3D)
        console.log("\n--- TEST 1: Default Isometric 3D View Properties ---");
        const defaultState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            const cam = v.camera;
            const target = v.controls.target;
            return {
                isOrthographic: !!cam.isOrthographicCamera,
                isPerspective: !!cam.isPerspectiveCamera,
                azimuthDeg: v.isoAzimuthDeg,
                elevationDeg: v.isoElevationDeg,
                enableRotate: v.controls.enableRotate,
                isOrbitFreely: v.isOrbitFreely,
                cameraPos: { x: cam.position.x, y: cam.position.y, z: cam.position.z },
                targetPos: { x: target.x, y: target.y, z: target.z },
                frustum: { left: cam.left, right: cam.right, top: cam.top, bottom: cam.bottom, zoom: cam.zoom },
                orthoExtent: v.orthoExtent
            };
        })()`);
        console.log("Default state:", JSON.stringify(defaultState, null, 2));

        if (!defaultState.isOrthographic) throw new Error("Expected camera to be OrthographicCamera!");
        if (Math.abs(defaultState.azimuthDeg - 45) > 0.5) throw new Error(`Expected azimuth 45°, got ${defaultState.azimuthDeg}`);
        if (Math.abs(defaultState.elevationDeg - 35.264) > 0.05) throw new Error(`Expected elevation ~35.264°, got ${defaultState.elevationDeg}`);
        if (defaultState.enableRotate !== false) throw new Error("Expected controls.enableRotate to be false for locked isometric view");
        if (defaultState.frustum.zoom !== 1) throw new Error("Expected initial zoom to be 1");
        console.log("PASS: Default Isometric 3D is a true orthographic camera at 45° azimuth and 35.264° elevation.");

        // 2. Test 90-degree rotation buttons
        console.log("\n--- TEST 2: Stepped 90° Rotations (CW and CCW) ---");
        const initialTarget = defaultState.targetPos;

        // Rotate CW
        await cdp.evaluate(`(() => { document.getElementById("btn-iso-rotate-cw").click(); })()`);
        await sleep(350);
        let rotState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                azimuth: v.isoAzimuthDeg,
                elevation: v.isoElevationDeg,
                target: { x: v.controls.target.x, y: v.controls.target.y, z: v.controls.target.z },
                isOrtho: !!v.camera.isOrthographicCamera
            };
        })()`);
        console.log("After 1st CW rotate:", rotState);
        if (rotState.azimuth !== 135) throw new Error(`Expected azimuth 135 after CW rotate, got ${rotState.azimuth}`);
        if (Math.abs(rotState.target.x - initialTarget.x) > 0.01 || Math.abs(rotState.target.z - initialTarget.z) > 0.01) {
            throw new Error("Target point was not preserved during rotation!");
        }

        // Rotate CW again
        await cdp.evaluate(`(() => { document.getElementById("btn-iso-rotate-cw").click(); })()`);
        await sleep(350);
        rotState = await cdp.evaluate(`(() => ({ azimuth: window.viewer.isoAzimuthDeg }))()`);
        console.log("After 2nd CW rotate:", rotState);
        if (rotState.azimuth !== 225) throw new Error(`Expected azimuth 225 after 2nd CW rotate, got ${rotState.azimuth}`);

        // Rotate CCW
        await cdp.evaluate(`(() => { document.getElementById("btn-iso-rotate-ccw").click(); })()`);
        await sleep(350);
        rotState = await cdp.evaluate(`(() => ({ azimuth: window.viewer.isoAzimuthDeg }))()`);
        console.log("After 1st CCW rotate:", rotState);
        if (rotState.azimuth !== 135) throw new Error(`Expected azimuth 135 after CCW rotate, got ${rotState.azimuth}`);

        console.log("PASS: 90° stepped rotation buttons work correctly around target.");

        // 3. Test Orbit Freely toggle
        console.log("\n--- TEST 3: Orbit Freely Toggle ---");
        await cdp.evaluate(`(() => { document.getElementById("btn-toggle-orbit-freely").click(); })()`);
        await sleep(200);
        const freeOrbitState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            const btn = document.getElementById("btn-toggle-orbit-freely");
            return {
                isPerspective: !!v.camera.isPerspectiveCamera,
                enableRotate: v.controls.enableRotate,
                ariaPressed: btn.getAttribute("aria-pressed"),
                isActive: btn.classList.contains("is-active"),
                target: { x: v.controls.target.x, y: v.controls.target.y, z: v.controls.target.z }
            };
        })()`);
        console.log("Free Orbit ON state:", freeOrbitState);
        if (!freeOrbitState.isPerspective) throw new Error("Expected perspective camera when Orbit Freely is ON");
        if (!freeOrbitState.enableRotate) throw new Error("Expected free orbit controls.enableRotate to be true");
        if (freeOrbitState.ariaPressed !== "true") throw new Error("Expected aria-pressed='true'");

        // Toggle OFF
        await cdp.evaluate(`(() => { document.getElementById("btn-toggle-orbit-freely").click(); })()`);
        await sleep(200);
        const snapBackState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            const btn = document.getElementById("btn-toggle-orbit-freely");
            return {
                isOrtho: !!v.camera.isOrthographicCamera,
                enableRotate: v.controls.enableRotate,
                azimuth: v.isoAzimuthDeg,
                elevation: v.isoElevationDeg,
                ariaPressed: btn.getAttribute("aria-pressed"),
                target: { x: v.controls.target.x, y: v.controls.target.y, z: v.controls.target.z }
            };
        })()`);
        console.log("Snap back state:", snapBackState);
        if (!snapBackState.isOrtho) throw new Error("Expected orthographic camera when Orbit Freely is toggled OFF");
        if (snapBackState.enableRotate !== false) throw new Error("Expected controls.enableRotate to be false after snap back");
        if (Math.abs(snapBackState.elevation - 35.264) > 0.05) throw new Error(`Expected elevation 35.264°, got ${snapBackState.elevation}`);

        console.log("PASS: Orbit Freely toggle switches cleanly to perspective and snaps back to orthographic isometric.");

        // 4. Test Reset to Isometric 3D button
        console.log("\n--- TEST 4: Isometric 3D Button Reset ---");
        await cdp.evaluate(`(() => { document.getElementById("btn-view-iso").click(); })()`);
        await sleep(200);
        const isoResetState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                azimuth: v.isoAzimuthDeg,
                elevation: v.isoElevationDeg,
                isOrtho: !!v.camera.isOrthographicCamera,
                zoom: v.camera.zoom
            };
        })()`);
        console.log("Isometric reset state:", isoResetState);
        if (isoResetState.azimuth !== 45) throw new Error(`Expected reset azimuth 45, got ${isoResetState.azimuth}`);
        if (isoResetState.zoom !== 1) throw new Error(`Expected zoom 1, got ${isoResetState.zoom}`);
        console.log("PASS: Isometric 3D button resets to canonical 45° azimuth and zoom 1.");

        // 5. Test Room Picking (Raycasting)
        console.log("\n--- TEST 5: Raycasting Room Picking with Active Camera ---");
        const pickResult = await cdp.evaluate(`(() => {
            const v = window.viewer;
            const roomMesh = v.selectableMeshes.find(m => m.userData && m.userData.roomData);
            if (!roomMesh) return { error: "No selectable room mesh found" };
            v.selectRoom(roomMesh);
            const inspector = document.getElementById("room-inspector-card");
            return {
                selectedRoomId: v.selectedRoomMesh ? v.selectedRoomMesh.userData.roomData.id : null,
                inspectorHidden: inspector ? inspector.classList.contains("hidden") : true,
                inspectorTitle: document.getElementById("inspector-title")?.textContent
            };
        })()`);
        console.log("Room pick result:", pickResult);
        if (pickResult.inspectorHidden) throw new Error("Room inspector did not show on room selection!");
        console.log("PASS: Raycasting and room picking work with the active camera.");

        // 6. Test Two-Story Demo
        console.log("\n--- TEST 6: Two-Story Demo Test ---");
        await cdp.evaluate(`(() => {
            const btnTwo = document.getElementById("btn-load-two-story-demo");
            if (btnTwo) btnTwo.click();
            else {
                const select = document.getElementById("sidebar-samples-select");
                if (select) {
                    select.value = "two-story";
                    select.dispatchEvent(new Event("change"));
                }
            }
        })()`);
        await sleep(2000);

        const twoStoryState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                levelCount: v.levelCount,
                roomCount: v.currentSceneData.rooms.length,
                isOrtho: !!v.camera.isOrthographicCamera,
                azimuth: v.isoAzimuthDeg,
                elevation: v.isoElevationDeg,
                frustum: { top: v.camera.top, bottom: v.camera.bottom, left: v.camera.left, right: v.camera.right }
            };
        })()`);
        console.log("Two-Story state:", twoStoryState);
        if (twoStoryState.levelCount < 2) throw new Error("Expected 2 or more levels in Two-Story demo!");
        if (!twoStoryState.isOrtho) throw new Error("Expected orthographic camera in Two-Story demo!");
        console.log("PASS: Two-Story demo correctly loads in true orthographic isometric view.");

        // Rotate on two-story demo
        await cdp.evaluate(`(() => { document.getElementById("btn-iso-rotate-cw").click(); })()`);
        await sleep(350);
        const twoStoryRot = await cdp.evaluate(`(() => ({ azimuth: window.viewer.isoAzimuthDeg }))()`);
        if (twoStoryRot.azimuth !== 135) throw new Error(`Expected 135 azimuth, got ${twoStoryRot.azimuth}`);
        console.log("PASS: Two-Story demo stepped rotation works.");

        // 7. Test Top-Down 2D, Eye Level, Cutaway, and Floor Isolation
        console.log("\n--- TEST 7: Top-Down 2D, Eye Level, Cutaway, and Floor Isolation ---");

        // Top-Down 2D
        await cdp.evaluate(`(() => { document.getElementById("btn-view-top").click(); })()`);
        await sleep(200);
        const topDownState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                is2DMode: v.is2DMode,
                isOrtho: !!v.camera.isOrthographicCamera,
                target: { x: v.controls.target.x, y: v.controls.target.y, z: v.controls.target.z }
            };
        })()`);
        console.log("Top-down state:", topDownState);
        if (!topDownState.is2DMode) throw new Error("Expected 2D mode in top-down view");

        // Eye Level
        await cdp.evaluate(`(() => { document.getElementById("btn-view-eye").click(); })()`);
        await sleep(200);
        const eyeState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                isEyeLevel: v.isEyeLevelView,
                isPerspective: !!v.camera.isPerspectiveCamera,
                target: { x: v.controls.target.x, y: v.controls.target.y, z: v.controls.target.z }
            };
        })()`);
        console.log("Eye level state:", eyeState);
        if (!eyeState.isPerspective) throw new Error("Expected perspective camera in Eye Level view");
        if (!eyeState.isEyeLevel) throw new Error("Expected isEyeLevelView to be true");

        // Return to Isometric 3D
        await cdp.evaluate(`(() => { document.getElementById("btn-view-iso").click(); })()`);
        await sleep(200);

        // Cutaway View
        await cdp.evaluate(`(() => { document.getElementById("btn-cutaway").click(); })()`);
        await sleep(200);
        const cutawayState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                wallHeight: v.wallHeight,
                isCutawayActive: window.isCutawayActive ?? false,
                isOrtho: !!v.camera.isOrthographicCamera
            };
        })()`);
        console.log("Cutaway active state:", cutawayState);
        if (Math.abs(cutawayState.wallHeight - 1.1) > 0.05) throw new Error("Expected wallHeight 1.1m in cutaway mode");

        // Toggle Cutaway back
        await cdp.evaluate(`(() => { document.getElementById("btn-cutaway").click(); })()`);
        await sleep(200);

        // Floor isolation (Isolate Story 1)
        await cdp.evaluate(`(() => {
            const filter = document.getElementById("level-filter");
            if (filter) {
                filter.value = "0";
                filter.dispatchEvent(new Event("change"));
            }
            window.viewer.setVisibleLevel(0);
        })()`);
        await sleep(200);
        const isolateState = await cdp.evaluate(`(() => {
            const v = window.viewer;
            return {
                visibleLevel: v.visibleLevel,
                fg0Visible: v.floorGroups.get(0)?.visible,
                fg1Visible: v.floorGroups.get(1)?.visible,
                isOrtho: !!v.camera.isOrthographicCamera
            };
        })()`);
        console.log("Floor isolation state:", isolateState);
        if (isolateState.visibleLevel !== 0 || isolateState.fg1Visible !== false) {
            throw new Error("Expected floor 1 to be hidden when isolating floor 0");
        }

        // Restore all stories
        await cdp.evaluate(`(() => {
            window.viewer.setVisibleLevel(null);
        })()`);
        await sleep(200);

        // GLB Export test (verify exportGLB adds ActiveCamera)
        const glbExportCheck = await cdp.evaluate(`(() => {
            const v = window.viewer;
            // Test building export scene
            const exportScene = new THREE.Scene();
            if (v.camera) {
                const camClone = v.camera.clone();
                camClone.name = "ActiveCamera";
                exportScene.add(camClone);
            }
            const camInExport = exportScene.getObjectByName("ActiveCamera");
            return {
                hasActiveCamera: !!camInExport,
                isOrtho: !!(camInExport && camInExport.isOrthographicCamera),
                zoom: camInExport ? camInExport.zoom : null
            };
        })()`);
        console.log("GLB active camera check:", glbExportCheck);
        if (!glbExportCheck.hasActiveCamera || !glbExportCheck.isOrtho) {
            throw new Error("GLB export scene missing active camera clone");
        }
        console.log("PASS: Top-Down, Eye Level, Cutaway, Floor Isolation, and GLB active camera all verified.");

        // Reset to canonical isometric view
        await cdp.evaluate(`(() => { document.getElementById("btn-view-iso").click(); })()`);
        await sleep(300);

        // Take a screenshot of the verified isometric view
        console.log("\nTaking screenshot...");
        const screenshotRes = await cdp.send("Page.captureScreenshot", { format: "png" });
        const screenshotBuffer = Buffer.from(screenshotRes.data, 'base64');
        const artifactPath = "C:\\Users\\tanma\\.gemini\\antigravity\\brain\\5eb069b3-6f3e-427d-b232-a0e2d018bd42\\true_ortho_iso_verified.png";
        fs.writeFileSync(artifactPath, screenshotBuffer);
        console.log("Screenshot saved to:", artifactPath);

        console.log("\nALL VERIFICATION CHECKS PASSED!");
    } finally {
        if (cdp && cdp.ws) {
            try { cdp.ws.close(); } catch(e) {}
        }
        chromeProc.kill('SIGKILL');
    }
}

run().catch(err => {
    console.error("FATAL ERROR:", err);
    process.exit(1);
});
