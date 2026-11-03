# FloorPlan3D

**Transforming 2D floor plans into explorable 3D environments.** FloorPlan3D turns an uploaded architectural plan into an editable scene that can be inspected, measured, and explored in a browser.

## Meta AI integration

- **Meta SAM 3.1** performs zero-shot, prompt-based segmentation for rooms, walls, doors, and windows. If a SAM request is unavailable or does not return useful masks, local OpenCV detection provides a fallback.
- **Muse Spark** helps classify room types, interpret labels in the plan, and answer questions grounded in the current scene. The app validates labels and uses generic labels or an offline scene lookup when the model is unavailable.
- Optional Muse Image and Muse Voice features can create a draft plan from a text prompt and transcribe a WAV question when the account and configured models support those calls.

The SAM request is implemented in `meta_sam_service.py` (`query_sam_concept`). Muse room labeling and scene questions are implemented in `baseten_service.py` (`label_rooms`, `answer_scene_question`). Both integrations are called by the Flask pipeline in `app.py`.

## How it works

1. Flask validates the uploaded plan and manages the processing job.
2. Meta SAM 3.1 and local OpenCV produce candidate image regions, depending on the configured mode and provider availability.
3. OpenCV and Shapely turn the detections into room, wall, and opening geometry in the `scene.json` format.
4. Muse Spark can add room labels and answer scene-grounded questions.
5. The Three.js frontend displays the scene and provides editing, walkthrough, measurement, and export tools.

## Prepared demo scenes

The **Meta AI Drafts** samples load instantly from saved scene data. They are included for reliable demos when the network or model service is unavailable. Loading a cached sample does not make a live model call; uploaded plans use the configured processing pipeline.

## Run locally

### Windows PowerShell

```powershell
git clone https://github.com/tanmaysandhu55/Meta-Global-hackthon-Project.git
cd Meta-Global-hackthon-Project
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

### macOS or Linux

```sh
git clone https://github.com/tanmaysandhu55/Meta-Global-hackthon-Project.git
cd Meta-Global-hackthon-Project
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python app.py
```

Open <http://127.0.0.1:5000> in your browser.

## Configure model access

Open `.env` and set the credentials and mode supported by your account:

```dotenv
MODEL_API_KEY=your_meta_model_api_key
MODEL_BASE_URL=https://api.meta.ai/v1
SAM_MODEL=sam-3.1
MUSE_MODEL=muse-spark-1.3
MOCK_AI=0
```

Use `MOCK_AI=1` for the prepared/offline demo. `MODEL_API_KEY` is the canonical Meta key setting; the application also recognizes the legacy `META_API_KEY` name. Muse Spark can use the Meta key when configured; a Baseten key is an optional provider fallback for Muse only. SAM 3.1 uses the Meta API key. Keep real credentials in your ignored `.env` file, never in source code, screenshots, or commits. `.env.example` contains placeholders only.

Restart the Flask app after changing `.env`. Without model credentials, prepared samples and local OpenCV processing remain available; room names fall back to generic labels when Muse is unavailable.

## Limitations

Segmentation works best on clean, high-contrast plans with clear room boundaries. Complex drawings, text, furniture, low contrast, and open boundaries can affect detections. Scale, room areas, doors, windows, and generated geometry are estimates; review and correct them against the source plan. This prototype is for visualization and exploration, not construction, code-compliance, evacuation, or safety decisions.

## Tests

Run the local test suite with:

```sh
python -m pytest -q
```

Provider calls in tests should use mocks; running the tests does not require a live API key.

## About

Built by Tanmay Sandhu for the Meta Global AI Developer Hackathon. Thanks for trying FloorPlan3D—feedback and careful review of the generated geometry are welcome.
