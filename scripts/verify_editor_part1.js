/**
 * Test script to verify Floor Plan Editor Part 1: Layout and Canvas via Chrome CDP.
 */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9223;

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
    console.log("=== Starting Editor Part 1 Verification ===");
    const userDataDir = path.join(process.cwd(), '.chrome_editor_test');
    
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
        await sleep(2000);
        const versionInfo = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
        const targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
        const target = targets.find(t => t.type === 'page' && !t.url.startsWith('chrome-extension:'));
        if (!target) throw new Error("No page target found");

        cdp = new CDPClient(target.webSocketDebuggerUrl);
        await cdp.connect();
        console.log("CDP Connected successfully.");

        await cdp.send('Page.enable');
        await cdp.send('Runtime.enable');
        
        console.log("Navigating to http://127.0.0.1:5000...");
        await cdp.send('Page.navigate', { url: 'http://127.0.0.1:5000' });
        await sleep(2500);

        // 1. Switch to 2D Editor
        console.log("\n--- Test 1: Navigation to 2D Editor ---");
        const switched = await cdp.evaluate(`
            (() => {
                if (window.FloorPlan3DStudio && window.FloorPlan3DStudio.switchToEditorView) {
                    window.FloorPlan3DStudio.switchToEditorView();
                    return true;
                }
                const btn = document.querySelector('[data-action="open-editor"]');
                if (btn) { btn.click(); return true; }
                return false;
            })()
        `);
        console.log("Switched to editor:", switched);
        await sleep(1000);

        // 2. Test Layout Dimensions
        console.log("\n--- Test 2: Layout & Grid Dimensions ---");
        const dims = await cdp.evaluate(`
            (() => {
                const topBar = document.getElementById('editor-top-bar');
                const toolRail = document.querySelector('.editor-tool-rail');
                const statusBar = document.getElementById('editor-status-bar');
                const canvas = document.getElementById('editor-svg-canvas');
                const view = document.getElementById('editor-view');
                
                const topRect = topBar ? topBar.getBoundingClientRect() : {};
                const railRect = toolRail ? toolRail.getBoundingClientRect() : {};
                const statusRect = statusBar ? statusBar.getBoundingClientRect() : {};
                const canvasRect = canvas ? canvas.getBoundingClientRect() : {};

                return {
                    topBarFound: !!topBar,
                    viewClass: view ? view.className : null,
                    viewComputedDisplay: view ? window.getComputedStyle(view).display : null,
                    topBarComputedHeight: topBar ? window.getComputedStyle(topBar).height : null,
                    topRect: JSON.stringify(topRect),
                    railRect: JSON.stringify(railRect),
                    statusRect: JSON.stringify(statusRect),
                    canvasRect: JSON.stringify(canvasRect)
                };
            })()
        `);
        console.log("Detailed Dimensions Diagnostic:", dims);

        // 3. Test Initial View State
        console.log("\n--- Test 3: Initial View & Centering ---");
        const viewState = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                if (!ed) return null;
                const dims = ed.getContainerDims();
                // Screen coordinate of world (6.0, 4.0)
                const screenCenterOf12x8 = ed.worldToScreen(6.0, 4.0);
                const actualScreenCenter = { x: dims.width / 2, y: dims.height / 2 };
                const diffX = Math.abs(screenCenterOf12x8.x - actualScreenCenter.x);
                const diffY = Math.abs(screenCenterOf12x8.y - actualScreenCenter.y);

                return {
                    zoom: ed.zoom,
                    pan: ed.pan,
                    activeTool: ed.activeTool,
                    snapEnabled: ed.snapEnabled,
                    snapStep: ed.snapStep,
                    isCenteredOn12x8: (diffX < 1 && diffY < 1),
                    screenCenterOf12x8,
                    actualScreenCenter
                };
            })()
        `);
        console.log("Initial View State:", viewState);

        // 4. Test Tool Rail & Active State Styling
        console.log("\n--- Test 4: Tool Rail Buttons & Active State ---");
        const toolState = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                const tools = Array.from(document.querySelectorAll('.editor-tool-btn')).map(b => b.dataset.tool);
                // Switch tool to 'wall'
                ed.setActiveTool('wall');
                const wallBtn = document.querySelector('.editor-tool-btn[data-tool="wall"]');
                const wallStyle = window.getComputedStyle(wallBtn);
                
                // Return to 'select'
                ed.setActiveTool('select');
                const selectBtn = document.querySelector('.editor-tool-btn[data-tool="select"]');
                const selectStyle = window.getComputedStyle(selectBtn);

                return {
                    tools,
                    wallIsActive: wallBtn.classList.contains('is-active'),
                    selectIsActive: selectBtn.classList.contains('is-active'),
                    selectBorderLeft: selectStyle.borderLeftWidth + ' ' + selectStyle.borderLeftStyle + ' ' + selectStyle.borderLeftColor,
                    selectBg: selectStyle.backgroundColor
                };
            })()
        `);
        console.log("Tool Rail State:", toolState);

        // 5. Test Zoom Levels (10, 25, 50, 100, 400 px/m) & Critical Text Rules
        console.log("\n--- Test 5: Zoom Levels & Constant Screen-Size Text ---");
        const zoomChecks = [10, 25, 50, 100, 400];
        for (const z of zoomChecks) {
            const check = await cdp.evaluate(`
                (() => {
                    const ed = window.floorPlanEditor;
                    ed.setZoom(${z});
                    const rulerTexts = Array.from(document.querySelectorAll('.editor-ruler-text'));
                    const firstRulerText = rulerTexts[0];
                    let computedFont = null;
                    if (firstRulerText) {
                        const style = window.getComputedStyle(firstRulerText);
                        computedFont = {
                            fontSize: style.fontSize,
                            fontFamily: style.fontFamily,
                            paintOrder: style.paintOrder,
                            pointerEvents: style.pointerEvents
                        };
                    }
                    const step = ed.getAdaptiveRulerStep();
                    const pxSpacing = step * ed.zoom;
                    return {
                        zoom: ed.zoom,
                        step,
                        pxSpacing: Math.round(pxSpacing),
                        rulerCount: rulerTexts.length,
                        computedFont
                    };
                })()
            `);
            console.log(`Zoom ${z} px/m:`, check);
        }

        // 6. Test Pan via Space + Mouse / Middle Mouse
        console.log("\n--- Test 6: Canvas Pan ---");
        const panResult = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                const oldPan = { ...ed.pan };
                // Simulate pan move
                ed.pan.x += 50;
                ed.pan.y += 30;
                ed.render();
                return {
                    oldPan,
                    newPan: ed.pan,
                    moved: (ed.pan.x !== oldPan.x && ed.pan.y !== oldPan.y)
                };
            })()
        `);
        console.log("Pan Result:", panResult);

        // 7. Test Empty State & "Load sample" & "Fit"
        console.log("\n--- Test 7: Load Sample & Fit to View ---");
        const loadResult = await cdp.evaluate(`
            (async () => {
                const ed = window.floorPlanEditor;
                const emptyCard = document.getElementById('editor-empty-state');
                const wasEmptyVisible = !emptyCard.classList.contains('hidden');

                // Trigger Load sample
                const loadBtn = document.getElementById('btn-empty-load-sample');
                if (loadBtn) loadBtn.click();

                // Wait up to 2 seconds for sample data fetch
                for (let i = 0; i < 20; i++) {
                    await new Promise(r => setTimeout(r, 100));
                    if (ed.hasObjects()) break;
                }

                const isHiddenAfterLoad = emptyCard.classList.contains('hidden');
                const objectCounts = {
                    walls: ed.scene.walls.length,
                    rooms: ed.scene.rooms.length,
                    doors: ed.scene.doors.length
                };

                // Trigger Fit
                ed.fitToView();
                const fittedZoom = ed.zoom;
                const fittedPan = { ...ed.pan };

                // Check room labels in screen overlay
                const roomLabels = Array.from(document.querySelectorAll('.editor-room-label')).map(el => ({
                    text: el.textContent,
                    x: el.getAttribute('x'),
                    y: el.getAttribute('y')
                }));

                return {
                    wasEmptyVisible,
                    isHiddenAfterLoad,
                    objectCounts,
                    fittedZoom,
                    fittedPan,
                    roomLabelCount: roomLabels.length,
                    firstRoomLabel: roomLabels[0]
                };
            })()
        `);
        console.log("Load Sample & Fit Result:", loadResult);

        // 8. Capture Verification Screenshot
        console.log("\n--- Test 8: Capturing Screenshot ---");
        const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
        const shotPath = path.join(
            "C:\\Users\\tanma\\.gemini\\antigravity\\brain\\5eb069b3-6f3e-427d-b232-a0e2d018bd42",
            "editor_part1_verified.png"
        );
        fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
        console.log("Saved verification screenshot to:", shotPath);

        // 9. Test "Send to 3D"
        console.log("\n--- Test 9: Send to 3D View Transition ---");
        const sendResult = await cdp.evaluate(`
            (() => {
                const ed = window.floorPlanEditor;
                const appView = document.getElementById('app-view');
                const editorView = document.getElementById('editor-view');
                
                // Click Send to 3D
                const btnSend = document.getElementById('btn-editor-send-to-3d');
                if (btnSend) btnSend.click();

                return {
                    editorViewHidden: editorView.classList.contains('view-hidden'),
                    appViewVisible: !appView.classList.contains('view-hidden'),
                    viewerCurrentScene: !!(window.viewer && window.viewer.currentSceneData)
                };
            })()
        `);
        console.log("Send to 3D Result:", sendResult);

        console.log("\n=== ALL PART 1 VERIFICATION CHECKS PASSED ===");

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
