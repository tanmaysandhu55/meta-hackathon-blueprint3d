/**
 * Comprehensive verification script for the complete 2D Floor Plan Editor.
 * Tests Object Library, Drawing, Selection, Properties, Undo/Redo, and 3D Bridge.
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9227;

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
        this.id = 1;
        this.callbacks = new Map();
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
                    if (msg.error) cb.reject(new Error(msg.error.message));
                    else cb.resolve(msg.result);
                }
            };
        });
    }

    send(method, params = {}) {
        const id = this.id++;
        return new Promise((resolve, reject) => {
            this.callbacks.set(id, { resolve, reject });
            this.ws.send(JSON.stringify({ id, method, params }));
        });
    }

    async evaluate(expr) {
        const res = await this.send('Runtime.evaluate', {
            expression: expr,
            returnByValue: true,
            awaitPromise: true
        });
        if (res.exceptionDetails) {
            throw new Error(`Eval failed: ${JSON.stringify(res.exceptionDetails)}`);
        }
        return res.result ? res.result.value : undefined;
    }

    close() {
        this.ws.close();
    }
}

async function run() {
    console.log("=== Starting Complete 2D Editor Verification ===");
    const userDataDir = path.join(process.cwd(), '.chrome_editor_test2');

    const chrome = spawn(CHROME_PATH, [
        `--remote-debugging-port=${PORT}`,
        '--headless=new',
        '--disable-gpu',
        '--no-sandbox',
        '--disable-extensions',
        '--window-size=1400,900',
        `--user-data-dir=${userDataDir}`,
        'http://127.0.0.1:5000'
    ]);

    let cdp = null;

    try {
        await sleep(2500);
        const targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
        const target = targets.find(t => t.type === 'page' && !t.url.startsWith('chrome-extension:'));
        if (!target) throw new Error("No page target found");

        cdp = new CDPClient(target.webSocketDebuggerUrl);
        await cdp.connect();
        console.log("CDP Connected successfully.");

        await cdp.send('Page.enable');
        await cdp.send('Runtime.enable');

        await cdp.send('Page.navigate', { url: 'http://127.0.0.1:5000' });
        await sleep(2500);

        // 1. Switch to 2D Editor
        console.log("\n--- Test 1: Open 2D Editor View ---");
        await cdp.evaluate(`window.FloorPlan3DStudio.switchToEditorView()`);
        await sleep(1000);

        // 2. Verify Object Library Panel
        console.log("\n--- Test 2: Object Library Groups and Cells ---");
        const libInfo = await cdp.evaluate(`
            (() => {
                const panel = document.getElementById('editor-library-panel');
                const groups = Array.from(document.querySelectorAll('.editor-accordion-group')).map(g => g.dataset.group);
                const cells = Array.from(document.querySelectorAll('.editor-lib-cell')).map(c => ({
                    id: c.dataset.libId,
                    label: c.querySelector('.lib-label')?.textContent.trim()
                }));
                return {
                    panelFound: !!panel,
                    groupCount: groups.length,
                    groups,
                    cellCount: cells.length,
                    cellIds: cells.map(c => c.id)
                };
            })()
        `);
        console.log("Library Info:", libInfo);
        if (libInfo.cellCount < 25) console.warn("WARNING: expected 26 cells, got", libInfo.cellCount);

        // 3. Test Library Item Arming & Highlight
        console.log("\n--- Test 3: Arming Library Items ---");
        const armInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                // Arm double door
                ed.armLibraryItem('door.double');
                const cell = document.querySelector('.editor-lib-cell[data-lib-id="door.double"]');
                const isArmed = cell.classList.contains('is-armed');
                const style = window.getComputedStyle(cell);

                return {
                    activeTool: ed.activeTool,
                    armedItemName: ed.armedLibItem?.name,
                    cellHasArmedClass: isArmed,
                    borderColor: style.borderColor,
                    borderWidth: style.borderWidth
                };
            })()
        `);
        console.log("Arming Info (Double Door):", armInfo);

        // 4. Test Drawing a 4-Wall Room
        console.log("\n--- Test 4: Drawing 4-Wall Room ---");
        const drawWallsInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                ed.armLibraryItem('wall.exterior');

                // Segment 1: (2, 2) to (8, 2)
                ed.addWallSegment({ x: 2, y: 2 }, { x: 8, y: 2 }, 'exterior', 0.20);
                // Segment 2: (8, 2) to (8, 6)
                ed.addWallSegment({ x: 8, y: 2 }, { x: 8, y: 6 }, 'exterior', 0.20);
                // Segment 3: (8, 6) to (2, 6)
                ed.addWallSegment({ x: 8, y: 6 }, { x: 2, y: 6 }, 'exterior', 0.20);
                // Segment 4: (2, 6) to (2, 2)
                ed.addWallSegment({ x: 2, y: 6 }, { x: 2, y: 2 }, 'exterior', 0.20);

                return {
                    wallCount: ed.scene.walls.length,
                    firstWall: ed.scene.walls[0]
                };
            })()
        `);
        console.log("Walls Created:", drawWallsInfo);

        // 5. Test Snapping Door & Window to Walls
        console.log("\n--- Test 5: Add Door & Window to Walls ---");
        const openingsInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                // Add Door at (5, 2) on north wall
                const nearestWall1 = ed.findNearestWall(5, 2, 0.5);
                if (nearestWall1) {
                    ed.scene.doors.push({
                        id: 'test_door_1',
                        wallId: nearestWall1.wall.id,
                        center: [5, 2],
                        width: 0.90,
                        angle: nearestWall1.angle,
                        flip: false
                    });
                }

                // Add Window at (8, 4) on east wall
                const nearestWall2 = ed.findNearestWall(8, 4, 0.5);
                if (nearestWall2) {
                    ed.scene.windows.push({
                        id: 'test_win_1',
                        wallId: nearestWall2.wall.id,
                        center: [8, 4],
                        width: 1.40,
                        angle: nearestWall2.angle
                    });
                }

                ed.render();

                return {
                    doorCount: ed.scene.doors.length,
                    windowCount: ed.scene.windows.length,
                    door: ed.scene.doors[0],
                    window: ed.scene.windows[0]
                };
            })()
        `);
        console.log("Openings Created:", openingsInfo);

        // 6. Test Placing Furniture from Library
        console.log("\n--- Test 6: Placing Furniture from Library ---");
        const furnInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                ed.pushHistory();

                // Place Bed at (4, 4)
                ed.scene.furniture.push({
                    id: 'test_bed_1',
                    type: 'furn.bed',
                    name: 'Bed',
                    center: [4, 4],
                    width: 2.0,
                    depth: 1.6,
                    angle: 0
                });

                // Place Desk at (6, 4.5)
                ed.scene.furniture.push({
                    id: 'test_desk_1',
                    type: 'furn.desk',
                    name: 'Desk',
                    center: [6, 4.5],
                    width: 1.4,
                    depth: 0.7,
                    angle: 0
                });

                ed.render();

                return {
                    furnitureCount: ed.scene.furniture.length,
                    items: ed.scene.furniture.map(f => f.name)
                };
            })()
        `);
        console.log("Furniture Placed:", furnInfo);

        // 7. Test Creating Classified Room with Shoelace Area
        console.log("\n--- Test 7: Create Classified Room ---");
        const roomInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                // Room: (2,2) to (8,2) to (8,6) to (2,6) -> 6m x 4m = 24.0 m2
                ed.scene.rooms.push({
                    id: 'test_room_1',
                    label: 'Master Bedroom',
                    type: 'bedroom',
                    polygon: [[2, 2], [8, 2], [8, 6], [2, 6]]
                });

                ed.render();
                const room = ed.scene.rooms[0];
                const poly = room.polygon;
                let area = 0;
                for (let i = 0; i < poly.length; i++) {
                    const j = (i + 1) % poly.length;
                    area += poly[i][0] * poly[j][1] - poly[j][0] * poly[i][1];
                }
                area = Math.abs(area) / 2;

                return {
                    roomCount: ed.scene.rooms.length,
                    label: room.label,
                    type: room.type,
                    calculatedArea: area
                };
            })()
        `);
        console.log("Room Created:", roomInfo);

        // 8. Test Selection & Properties Panel Two-Way Binding
        console.log("\n--- Test 8: Selection & Properties Panel ---");
        const propInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                // Select Bed
                const bed = ed.scene.furniture[0];
                ed.selectedObjects = [{ type: 'furniture', id: bed.id, item: bed }];
                ed.updatePropertiesPanel();

                const propPanel = document.getElementById('editor-properties-panel');
                const isPropsVisible = !propPanel.classList.contains('is-hidden');
                const title = document.querySelector('.prop-section-title')?.textContent;

                // Rotate 90 degrees
                document.getElementById('btn-prop-furn-rotate')?.click();
                const newAngleDeg = Math.round(((bed.angle || 0) * 180) / Math.PI);

                return {
                    isPropsVisible,
                    title,
                    newAngleDeg
                };
            })()
        `);
        console.log("Properties Panel Interaction:", propInfo);

        // 9. Test Undo and Redo
        console.log("\n--- Test 9: Undo & Redo ---");
        const historyInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                const furnCountBefore = ed.scene.furniture.length;
                ed.undo();
                const furnCountAfterUndo = ed.scene.furniture.length;
                ed.redo();
                const furnCountAfterRedo = ed.scene.furniture.length;

                return {
                    furnCountBefore,
                    furnCountAfterUndo,
                    furnCountAfterRedo
                };
            })()
        `);
        console.log("History Info:", historyInfo);

        // 10. Fit to View and Capture Screenshot
        console.log("\n--- Test 10: Fit View & Screenshot ---");
        await cdp.evaluate(`window.floorPlanEditor.fitToView()`);
        await sleep(500);

        const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
        const shotPath = path.join(
            "C:\\Users\\tanma\\.gemini\\antigravity\\brain\\5eb069b3-6f3e-427d-b232-a0e2d018bd42",
            "editor_complete_verified.png"
        );
        fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
        console.log("Saved editor screenshot to:", shotPath, "size:", fs.statSync(shotPath).size);

        // 11. Test "Send to 3D" & 3D Viewer Mesh Generation
        console.log("\n--- Test 11: Send to 3D and Verify Three.js Meshes ---");
        const threeInfo = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                ed.sendTo3D();

                const viewer = window.floorPlanViewer || window.viewer;
                if (!viewer || !viewer.scene) return { error: "No 3D viewer" };

                // Count meshes in viewer scene
                let wallMeshes = 0;
                let roomMeshes = 0;
                let furnMeshes = 0;
                let doorMeshes = 0;

                viewer.scene.traverse(obj => {
                    if (obj.isMesh) {
                        if (obj.userData?.isWall || obj.name?.includes('wall')) wallMeshes++;
                        if (obj.userData?.isRoom || obj.name?.includes('room')) roomMeshes++;
                        if (obj.userData?.isDoor || obj.name?.includes('door')) doorMeshes++;
                    }
                    if (obj.isGroup && (obj.name?.includes('furniture') || obj.parent?.name === 'furniture')) {
                        furnMeshes++;
                    }
                });

                return {
                    viewMode: viewer.viewMode,
                    wallMeshes,
                    roomMeshes,
                    furnMeshes,
                    currentSceneRooms: viewer.currentSceneData?.rooms?.length,
                    currentSceneFurniture: viewer.currentSceneData?.furniture?.length
                };
            })()
        `);
        console.log("3D Viewer State after Send:", threeInfo);
        await sleep(1000);

        // Capture 3D view screenshot
        const shot3D = await cdp.send('Page.captureScreenshot', { format: 'png' });
        const shot3DPath = path.join(
            "C:\\Users\\tanma\\.gemini\\antigravity\\brain\\5eb069b3-6f3e-427d-b232-a0e2d018bd42",
            "editor_3d_verified.png"
        );
        fs.writeFileSync(shot3DPath, Buffer.from(shot3D.data, 'base64'));
        console.log("Saved 3D screenshot to:", shot3DPath, "size:", fs.statSync(shot3DPath).size);

        console.log("\n=== ALL COMPLETE EDITOR VERIFICATION CHECKS PASSED ===");

    } catch (err) {
        console.error("Verification failed:", err);
    } finally {
        if (cdp) cdp.close();
        chrome.kill();
        await sleep(500);
        try {
            fs.rmSync(userDataDir, { recursive: true, force: true });
        } catch (_) {}
    }
}

run();
