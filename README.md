# FloorPlan3D

FloorPlan3D turns a 2D floor-plan image into a metric `scene.json` and a navigable Three.js view. The project has a prepared example for demos. Live segmentation requires a configured SAM service; the sample works without model API keys or inference calls. The page loads Three.js and Tailwind from CDNs, so the browser still needs network access to those assets.

## Current prototype

- **Offline demo:** loads the prepared sample plan, scene, segmentation overlay, room inspector, and 3D model without API keys.
- **Two-story demo:** loads the prepared plan as a stacked two-level building; use the story selector to inspect either floor or both together.
- **Live processing:** accepts PNG, JPG, and WebP images up to 10 MB, normalizes them to PNG, and runs SAM segmentation in a background job.
- **Geometry:** cleans masks, converts contours to meter coordinates, estimates scale from the median detected door width when enabled, and approximates walls from room outlines if no wall mask is returned.
- **Room labels:** uses the configured Modal classifier or Fireworks fallback. If neither returns usable labels, rooms stay generic and `scene.meta.warnings` explains the fallback.
- **Viewer:** renders floors, extruded walls, doors, windows, labels, shadows, cutaway height, room selection and focus, door-based shortest routes, scene JSON, and GLB export.

First-person walkthrough and robust segmentation across varied plans are not implemented yet. Room focus and routing depend on detected geometry and door connections, so they may be unavailable or inaccurate on some plans. Door and window positions are simplified markers; wall fallback geometry is an approximation. The multi-story scene format is supported, but live uploads are still interpreted as a single floor unless the input and processing pipeline provide per-level geometry.

## Architecture

```mermaid
flowchart LR
    A[Floor plan upload] --> B[Flask upload and validation]
    B --> C[Background job and status API]
    C --> D[SAM service: one request per concept]
    D --> E[OpenCV and Shapely geometry]
    E --> F[Optional Modal or Fireworks room labels]
    F --> G[scene.json and overlay data]
    G --> H[Three.js viewer]
    I[Prepared sample] --> G
```

The SAM adapter calls only Baseten using `BASETEN_API_KEY` and either `BASETEN_SAM_URL` or `BASETEN_MODEL_ID`. The model ID builds Baseten's standard production prediction URL (`https://model-<id>.api.baseten.co/production/predict`). The request body sends a base64 data URL in `image` and the segmentation phrase in `prompt`; the deployed SAM endpoint must accept that payload and return masks in the supported `masks`, `predictions`, or `output` response shape. The app does not call `api.meta.ai` and does not run local model inference.

Room labeling sends the plan image and room candidates to Muse Spark through Modal's OpenAI-compatible chat completions endpoint. Set `MODAL_MUSE_SPARK_URL` and `MODAL_MUSE_SPARK_MODEL` to the endpoint URL and model name shown in the Modal dashboard. For Modal proxy authentication, `MODAL_API_KEY` must contain a combined token in the documented `wk-<token-id>.ws-<token-secret>` form. If Modal is unavailable or returns unusable output, Fireworks Llama is used as a text/NLP classification fallback. Fireworks uses its OpenAI-compatible chat completions endpoint, `FIREWORKS_BASE_URL`, model ID, and `FIREWORKS_API_KEY`. When neither classifier is available, the scene uses generic labels and a warning.

> Configure only provider endpoints and model IDs you have verified for your account. The code’s Baseten adapter expects a response containing a `masks`, `predictions`, or `output` field; provider response formats can vary.

## Run the offline demo now

1. Install Python 3.11 or newer.
2. In PowerShell, create a project environment and install the dependencies. If your Python is installed somewhere else, replace the interpreter path with that Python 3.11+ executable:

   ```powershell
   & "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Start the app with `run.bat`, or run `.\.venv\Scripts\python.exe app.py` in PowerShell.
4. Open `http://127.0.0.1:5000` and choose **Load Hackathon Demo Plan**.
5. Try room focus and routing, room selection, the 2D overlay and scene JSON tabs, cutaway view, and GLB export.

Use the same interpreter for installation and startup. On some Windows setups, `python` can point to a separate distribution that does not have the packages installed.

The page shows **Offline demo mode** when no SAM credentials are configured. It disables live processing, but does not disable the prepared demo. Placeholder values in `.env.example` are blank so they cannot accidentally enable live processing.

## Configure live processing when your keys arrive

Copy `.env.example` to `.env`, then fill only the services you will use:

```ini
# Baseten SAM custom deployment
BASETEN_API_KEY=
# Set one of the following:
BASETEN_SAM_URL=
BASETEN_MODEL_ID=

# Modal Muse Spark Endpoint URL/model from the dashboard and proxy token
MODAL_API_KEY=
MODAL_MUSE_SPARK_URL=
MODAL_MUSE_SPARK_MODEL=

# Fireworks Llama 3 text/NLP (also used as classifier fallback)
FIREWORKS_API_KEY=
```

Keep `.env` private and never put keys in source files, screenshots, or commits. Restart Flask after editing `.env`. The page should then show **Live processing configured**. This confirms the Baseten key and endpoint settings are present; it does not confirm that the deployment is reachable or that its request/response schema matches the adapter. If no classifier is configured, processing still produces a scene with generic labels and a warning.

Live uploads use `POST /api/upload`, `GET /api/status/<job_id>`, and `GET /api/scene/<job_id>`. Uploads are limited to 10 MB and 20 megapixels. Supported formats are PNG, JPG, and WebP.

## Scale and geometry notes

Automatic scale estimation is enabled by default and assumes the median detected door width is 0.9 m. If doors cannot be detected reliably, the selected scale is used and the scene includes a warning. Uncheck the option to use the meters-per-pixel slider directly. In either mode, verify dimensions against a known measurement before relying on them.

Coordinates in `scene.json` are meters, with the source plan’s top-left as origin, x increasing right, and y increasing down. The viewer centers the geometry for display; exported JSON keeps the plan coordinates. Multi-story examples declare `meta.levels` and `meta.floorHeight`; each room, wall, door, and window can carry a zero-based `level`.

## Demo rehearsal

See [DEMO.md](DEMO.md) for a two-minute flow and recovery steps. Use the built-in sample if live keys or provider availability are uncertain. Describe the sample as prepared demo data, and live-upload results as model-assisted estimates.

## Project files

```text
app.py                    Flask UI, validation, background jobs, scene API
sam_service.py            SAM calls and room-classification adapter
cloud_services.py         Baseten, Modal, and Fireworks integrations
geometry_processor.py     Mask cleanup, polygon conversion, scale, doors, walls
demo_data.py              Prepared sample plan, scene, and overlays
templates/index.html      Single-page interface
static/js/app.js          Upload, progress, tabs, inspector, downloads
static/js/viewer.js       Three.js renderer and GLB export
```
