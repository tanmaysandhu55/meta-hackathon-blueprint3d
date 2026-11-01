# FloorPlan3D Audit Findings & Bug Report (Phase 1)

This report details the comprehensive audit conducted across the FloorPlan3D repository on branch `audit-and-keys`. Findings are organized and sorted by severity: **Blocker**, **Major**, and **Minor**.

---

## 1. Inventory & Architecture Overview

- **Backend**:
  - `app.py`: Flask web application providing the REST API (`/api/upload`, `/api/status/<job_id>`, `/api/scene/<job_id>`, `/api/sample`, `/api/sample/two-story`, `/api/scene/ask`, `/api/scene/insight`, `/api/generate-floorplan`, `/api/transcribe`).
  - `geometry_processor.py`: Metric transformation, polygon extraction from binary masks, wall generation, door/window detection, Shoelace area calculation.
  - `meta_sam_service.py`: Meta SAM 3.1 segmentation via the Responses API (`sam-3.1`) and mask parsing via `meta_sam_parser`.
  - `meta_media_service.py`: Muse Image generation (`muse-image-1.0`) and Muse Voice transcription (`muse-voice-transcribe-1.0`).
  - `baseten_service.py`: Legacy partner integration for room labeling and map queries (to be unified under official Meta Model API).
  - `segmentation_service.py`: OpenCV fallback segmentation when AI services are offline or disabled.
  - `demo_data.py`: Built-in sample scenes (single-story and two-story) and raster floor plan generator.
  - `usage_tracker.py`: Tracks token and inference call volume.
- **Frontend**:
  - `templates/index.html`: Studio shell with top bar, left sidebar, Three.js 3D viewport, 2D segmentation overlay, room inspector, and 2D floor plan editor modal dialogs.
  - `static/js/viewer.js`: Three.js 3D rendering engine (Orthographic isometric camera, perspective camera, cutaway, walkthrough, sunlight cycle, blueprint underlay, egress simulation, GLB exporter).
  - `static/js/app.js`: Application controller managing UI tabs, sample loading, file uploads, polling, calibration sliders, and inspection cards.
  - `static/js/editor.js`: 2D CAD floor plan editor with 7 object library groups (26 items), geometric snapping, properties inspector, and 3D sync bridge.
  - `static/js/landing.js`: Landing studio view controller, smooth scrolling, sample previews, and view switching.

---

## 2. Findings Sorted by Severity

### Severity: BLOCKER

#### BUG-01: Null Reference in Room Selection Callback
- **File**: `static/js/viewer.js`
- **Line**: 1935
- **Symptom**: `TypeError: Cannot read properties of undefined (reading 'roomData')` at `FloorPlanViewer.selectRoom()`.
- **Cause**: Line 1935 calls `window.onFloorPlanRoomSelected(roomMesh.userData.roomData);` without verifying that `roomMesh` or `roomMesh.userData` exists. If called programmatically with a room object or if `userData` is missing, the script throws an uncaught TypeError and halts execution.
- **Severity**: Blocker
- **Planned Fix**: Add safe optional chaining and fallback:
  ```javascript
  const roomData = roomMesh?.userData?.roomData || roomMesh?.userData?.room || (roomMesh && !roomMesh.isMesh ? roomMesh : null);
  if (typeof window.onFloorPlanRoomSelected === "function") {
      window.onFloorPlanRoomSelected(roomData);
  }
  ```

#### BUG-02: Missing DOM ID Causing Crash on Voice Transcription Error
- **File**: `static/js/app.js`
- **Lines**: 136, 716, 720, 728, 730
- **Symptom**: `TypeError: Cannot read properties of null (setting 'textContent')` when audio recording or transcription fails.
- **Cause**: `app.js` declares `const mapTranscriptionStatus = document.getElementById("map-transcription-status");` and sets `mapTranscriptionStatus.textContent = ...`, but `id="map-transcription-status"` does not exist in `templates/index.html` (the audio accordion element is named `map-audio-status` or missing).
- **Severity**: Blocker
- **Planned Fix**: Add `id="map-transcription-status"` to the voice audio status paragraph in `templates/index.html`, and add null guards in `app.js` before setting `textContent`.

#### BUG-03: Potential Uncaught Null Pointer in 3D Viewer Container Initialization
- **File**: `static/js/viewer.js`
- **Lines**: 148, 651
- **Symptom**: `TypeError: Cannot read properties of null (reading 'appendChild')` on early container access or demo load.
- **Cause**: `this.container` is fetched via `document.getElementById(container)` without checking if it is null before calling `this.container.appendChild(this.renderer.domElement)` and `this.container.appendChild(panel)` in `createFloorInfoPanel()`.
- **Severity**: Blocker
- **Planned Fix**: Add an explicit check in `FloorPlanViewer` constructor: if `!this.container`, log a clear `console.warn` and halt initialization gracefully. Guard `createFloorInfoPanel()` with `if (!this.container) return;`.

#### BUG-04: SAM Concept Prompts Violate Official Meta Model API Specification
- **File**: `meta_sam_service.py`
- **Lines**: 18-23
- **Symptom**: Concept requests sent to Meta SAM 3.1 may fail or yield degraded segmentation accuracy.
- **Cause**: The official Meta Model API documentation specifies that concept prompts for `sam-3.1` over `POST /v1/responses` must be ONE short singular noun-phrase (e.g. `"room"`, `"door"`, `"wall"`, `"window"`). `meta_sam_service.py` currently maps them to plurals:
  `CONCEPT_PROMPTS = {"room": "rooms", "wall": "walls", "door": "doors", "window": "windows"}`.
- **Severity**: Blocker
- **Planned Fix**: Update `CONCEPT_PROMPTS` to standard singular noun phrases per official Meta docs (`"room"`, `"door"`, `"window"`, `"wall"`, `"staircase"`, `"elevator"`, `"corridor"`, `"toilet"`).

#### BUG-05: Missing Central Configuration and Scattered API Key Names
- **Files**: `app.py`, `meta_sam_service.py`, `meta_media_service.py`, `baseten_service.py`, `.env.example`
- **Lines**: Multiple
- **Symptom**: Inconsistent environment variable lookups (`MODEL_API_KEY`, `META_API_KEY`, `BASETEN_API_KEY`, `BASETEN_MUSE_MODEL`). The app cannot cleanly switch between Mock and Live mode.
- **Cause**: There is no centralized `config.py`. Key names are fragmented across services, and `.env.example` still instructs users to configure removed/legacy variables.
- **Severity**: Blocker
- **Planned Fix**: Create a single `config.py` exposing verified defaults:
  - `MODEL_API_KEY` (unified variable name)
  - `MODEL_BASE_URL` (`https://api.meta.ai/v1`)
  - `SAM_MODEL` (`sam-3.1`)
  - `MUSE_MODEL` (`muse-spark-1.3`, verified Standard tier)
  - `MOCK_AI` (default 1)
  - `SAM_CONCEPTS` (`["room", "door", "window", "wall", "staircase", "elevator", "corridor", "toilet"]`)
  - `MAX_IMAGE_SIDE` (1500), `SAM_TIMEOUT` (75s), `MAX_PARALLEL` (4)
  Make the app start cleanly in `MOCK_AI=1` mode if no `.env` exists.

---

### Severity: MAJOR

#### BUG-06: Missing Global JSON Error Handlers on Flask Backend
- **File**: `app.py`
- **Lines**: 603-605
- **Symptom**: Network requests returning 400, 404, 405, or 500 receive HTML error pages instead of JSON, causing frontend `response.json()` to crash with `SyntaxError: Unexpected token '<'`.
- **Cause**: Only `@app.errorhandler(413)` is registered. All other HTTP errors fallback to default Flask HTML templates.
- **Severity**: Major
- **Planned Fix**: Register error handlers for 400, 404, 405, and 500 in `app.py` returning standard JSON: `{"success": false, "error": message, "code": HTTP_CODE}`.

#### BUG-07: Unguarded DOM Lookups and Feature Initialization in Frontend
- **File**: `static/js/app.js`
- **Lines**: 739-786, 890, 1324, 1514, 2075-2136
- **Symptom**: If any optional UI element is absent or temporarily hidden, script execution immediately aborts with an uncaught `TypeError: Cannot read properties of null (reading 'addEventListener')`.
- **Cause**: Over 25 DOM elements are accessed directly with `.addEventListener()` or property setters without checking whether the element exists.
- **Severity**: Major
- **Planned Fix**: Wrap each feature group's initialization in its own `try/catch` block, guard every `document.getElementById` with `if (el)` or optional chaining, and log a `console.warn` if an optional component is missing.

#### BUG-08: Memory Leak & Missing Teardown in Three.js Render Loop
- **File**: `static/js/viewer.js`
- **Lines**: 460-480
- **Symptom**: `animate()` initiates an unbound `requestAnimationFrame` loop without storing its handle, risking duplicate loops on scene reload and burning CPU/GPU.
- **Cause**: No `this.animationFrameId` is tracked, and no `destroy()` or `cancelAnimationFrame()` teardown exists for scene switches or page unloads.
- **Severity**: Major
- **Planned Fix**: Store `this.animationFrameId = requestAnimationFrame(...)`, add a `destroy()` method that cancels animation frames, disposes all renderer/scene resources, and removes global `window` event listeners (`resize`, `keydown`).

#### BUG-09: Missing Status Endpoint for Live/Mock Readiness
- **File**: `app.py`
- **Lines**: Missing endpoint
- **Symptom**: Frontend cannot dynamically determine whether live API keys are valid and ready, requiring manual template conditional rendering.
- **Cause**: `GET /api/config/status` is not implemented.
- **Severity**: Major
- **Planned Fix**: Implement `GET /api/config/status` returning non-secret metadata:
  ```json
  {
    "live_ready": false,
    "mock_mode": true,
    "key_configured": false,
    "sam_model": "sam-3.1",
    "muse_model": "muse-spark-1.3",
    "reasons": ["MODEL_API_KEY is not set"]
  }
  ```
  Ensure the API key itself is never exposed.

#### BUG-10: Incomplete `.gitignore` Coverage
- **File**: `.gitignore`
- **Lines**: 1-24
- **Symptom**: Project build/runtime artifacts (`cache/`, `out/`, `projects/`) can inadvertently be tracked by git.
- **Cause**: `.gitignore` lacks entries for `cache/`, `out/`, and `projects/`.
- **Severity**: Major
- **Planned Fix**: Append `cache/`, `out/`, and `projects/` to `.gitignore`.

#### BUG-11: Legacy Provider Mentions in UI and API
- **Files**: `templates/index.html` (lines 481, 550), `static/js/app.js` (line 197), `app.py` (lines 641, 673, 713)
- **Symptom**: UI badges and status captions display "Baseten" and "META_API_KEY", conflicting with official Meta Model API branding.
- **Cause**: Leftover text from previous provider implementations.
- **Severity**: Major
- **Planned Fix**: Replace mentions of `Baseten` and `META_API_KEY` with standard `Meta SAM 3.1` and `MODEL_API_KEY`.

---

### Severity: MINOR

#### BUG-12: Corrupted Encoding Characters in UI Status Strings
- **File**: `static/js/app.js`
- **Lines**: 187-190
- **Symptom**: Visual encoding glitch in status badges: `"MOCK MODE  PREPARED SAMPLE, NOT LIVE AI"`.
- **Cause**: Corrupted em-dash characters encoded as replacement characters (`\uFFFD`).
- **Severity**: Minor
- **Planned Fix**: Replace with clean ASCII dashes: `"MOCK MODE - PREPARED SAMPLE, NOT LIVE AI"`.

#### BUG-13: Unused Imports and Dead Variables
- **Files**: `demo_data.py` (lines 8, 10), `scripts/generate_samples_index.py` (line 9), `scripts/audit_emoji.py` (line 43)
- **Symptom**: Pyflakes static analysis warnings on unused imports (`io`, `base64`, `glob`) and unused variables.
- **Cause**: Uncleaned imports from refactored scripts.
- **Severity**: Minor
- **Planned Fix**: Remove unused imports and variables.

#### BUG-14: Production Warning for Tailwind CDN Script
- **File**: `templates/index.html`
- **Line**: 12
- **Symptom**: Browser console warning: `cdn.tailwindcss.com should not be used in production`.
- **Cause**: Standalone CDN script without production compilation.
- **Severity**: Minor
- **Planned Fix**: Document that Tailwind CDN is retained for lightweight hackathon demo delivery without Node build steps, while suppressing development noise where possible.

---

## 3. Plan of Execution for Phase 2 (Fixes)

Following your approval, fixes will be applied in strict severity order (Blockers -> Majors -> Minors), creating **one atomic git commit per fix**:

1. **Commit 1 (Blocker)**: Make `FloorPlanViewer.selectRoom()` null-safe in `viewer.js`.
2. **Commit 2 (Blocker)**: Add `map-transcription-status` ID in `index.html` and null-guards in `app.js`.
3. **Commit 3 (Blocker)**: Guard `FloorPlanViewer` container lookups and `createFloorInfoPanel()` in `viewer.js`.
4. **Commit 4 (Blocker)**: Update SAM 3.1 concept prompts to official singular noun-phrases in `meta_sam_service.py`.
5. **Commit 5 (Blocker)**: Implement unified `config.py` with `MODEL_API_KEY` and fallback `MOCK_AI=1`.
6. **Commit 6 (Major)**: Implement global JSON error handlers for 400, 404, 405, 500 in `app.py`.
7. **Commit 7 (Major)**: Wrap frontend feature initializations in isolated try/catch blocks and null-guards in `app.js`.
8. **Commit 8 (Major)**: Add Three.js animation frame tracking and `destroy()` teardown in `viewer.js`.
9. **Commit 9 (Major)**: Implement `/api/config/status` endpoint in `app.py` and hook status chip in `app.js`.
10. **Commit 10 (Major)**: Update `.gitignore` to cover `cache/`, `out/`, `projects/`.
11. **Commit 11 (Major)**: Remove legacy "Baseten" and "META_API_KEY" strings from UI and backend.
12. **Commit 12 (Minor)**: Fix corrupted dash characters in `app.js` and clean up unused imports in Python scripts.
