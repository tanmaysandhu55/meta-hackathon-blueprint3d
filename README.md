# FloorPlan3D

### From a 2D blueprint to an interactive 3D space

FloorPlan3D turns architectural floor-plan images into structured scene data and an explorable Three.js model. It brings visual review, room information, editing, and navigation into one browser-based workspace.

> **Built by Tanmay Sandhu for the Meta Global AI Developer Hackathon**

## The problem

A floor plan contains walls, rooms, doors, windows, labels, and connections, but those details are flattened into a drawing. Understanding how the spaces fit together can take time, especially for people who do not work with plans every day.

FloorPlan3D makes a plan easier to inspect by transforming detected features into a 3D scene while keeping review and correction tools close to the original drawing.

## What FloorPlan3D does

- Processes uploaded floor-plan images and displays detected rooms and architectural features.
- Shows room labels, floor levels, estimated areas, and connections.
- Provides 3D, top-down, and walkthrough views.
- Includes a 2D editor for reviewing and adjusting the plan.
- Previews routes through doors and between connected floors.
- Offers prepared **Meta AI Drafts** that load instantly for a dependable demo.

## Meta AI in the workflow

Meta models add image understanding and scene interpretation to the application:

- **Meta SAM 3.1** uses text prompts to segment image regions such as rooms, walls, doors, and windows.
- **Muse Spark** helps classify rooms and interpret plan context. **Ask This Map** uses the current scene to answer questions about rooms and connections.
- Optional **Muse Image** and **Muse Voice** features can draft a floor-plan image from text and transcribe WAV questions when the corresponding account access is configured.

The Flask backend coordinates model requests and processing. OpenCV handles image operations and fallback detection; Shapely constructs and validates geometry; Three.js renders the scene in the browser. See `meta_sam_service.py`, `baseten_service.py`, and `meta_media_service.py` for the model integration points.

## How it works

```text
Floor-plan image or text prompt
              ↓
      Flask upload and job API
              ↓
 Meta SAM 3.1 segmentation, when configured
     OpenCV detection and fallback processing
              ↓
       Shapely geometry processing
              ↓
 Muse Spark scene interpretation, when configured
              ↓
       Structured scene data
              ↓
 Three.js viewer, editor, and navigation
```

Which model steps run depends on the configured credentials and feature. Local processing and prepared scenes let users explore the project without making live model calls.

## Demo mode

The prepared **Meta AI Drafts** are cached scenes. They load immediately and do not call a model during loading. Uploaded plans use the active processing configuration. The interface indicates the current mode so a cached scene is not mistaken for a live inference result.

## Technology

| Component | Technology |
| --- | --- |
| Web application and API | Python, Flask |
| Model integrations | Meta SAM 3.1, Muse Spark; optional Muse Image and Muse Voice |
| Image processing | OpenCV, NumPy, Pillow |
| Geometry | Shapely |
| 3D viewer and editor | Three.js, JavaScript, HTML, CSS |
| Validation and tests | JSON Schema, pytest |

## Run locally

### Requirements

- Python 3.12 or newer
- Git
- A modern web browser

Prepared scenes and local fallback features can be explored without API credentials. Live model features require valid credentials and access to the relevant models.

### Windows (PowerShell)

```powershell
git clone https://github.com/tanmaysandhu55/meta-hackathon-blueprint3d.git
cd meta-hackathon-blueprint3d
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

### macOS or Linux

```sh
git clone https://github.com/tanmaysandhu55/meta-hackathon-blueprint3d.git
cd meta-hackathon-blueprint3d
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### Configure API access

Copy `.env.example` to `.env`, then enter the credentials and model IDs supported by your account for the features you want to use. Keep actual keys in `.env` and never commit them. Restart the Flask app after changing environment settings. The prepared scenes do not need API keys.

## Tests

Run the test suite from the project folder:

```sh
python -m pytest -q
```

Tests use local fixtures and mocked API responses; they do not require real credentials or make live model calls.

## Limitations

Results depend on the quality and style of the source drawing. Clear, high-contrast plans generally work best. Detected walls, openings, room boundaries, scale, and areas are estimates and may need correction. FloorPlan3D is a visualization prototype; its output is not intended for construction, safety decisions, evacuation planning, or code-compliance assessment.

## About

FloorPlan3D was built by **Tanmay Sandhu** for the **Meta Global AI Developer Hackathon**. The goal is to make architectural layouts easier to understand, review, and explore.
