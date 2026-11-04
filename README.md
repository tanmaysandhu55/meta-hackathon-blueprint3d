# 🏠 FloorPlan3D

### Transform 2D floor plans into interactive 3D spaces

FloorPlan3D is a web application for turning architectural floor-plan images into editable, explorable 3D scenes. It combines Meta model inference with computer-vision and geometry processing, then presents the result in a browser-based Three.js viewer.

---

## 🧠 Project Overview

Reading a floor plan means interpreting walls, openings, rooms, labels, and how spaces connect. That can be difficult when all the information is flattened into a 2D image. FloorPlan3D helps make the layout easier to understand by creating a 3D view that users can inspect, edit, and navigate.

## 🔍 What Problem Does It Address?

Floor plans are useful technical documents, but they can be hard to visualize for people who do not regularly work with architectural drawings. Reviewing a plan also involves checking many details across the image, including room boundaries, doors, windows, and floor connections.

FloorPlan3D provides an interactive way to explore those details while keeping the source plan and review workflow close at hand.

## 🛠️ What Can You Do?

- Upload a floor-plan image for processing.
- Review detected rooms, walls, doors, and windows.
- Inspect room labels, estimated areas, and floor levels.
- Explore a model in 3D, top-down, or first-person walkthrough views.
- Edit plan elements in the 2D editor.
- View door-based routes and cross-floor connections.
- Load prepared demo scenes instantly for presentations.

## 🤖 Meta AI Integration

Meta models contribute to the plan-understanding workflow:

- **Meta SAM 3.1** performs prompt-based segmentation to identify image regions for rooms and architectural features.
- **Muse Spark** supports room classification, scene interpretation, and the **Ask This Map** feature, which answers questions grounded in the current scene.
- Optional **Muse Image** and **Muse Voice** integrations support text-based draft-plan generation and WAV transcription when configured for the account.

Model requests are implemented in `meta_sam_service.py`, `baseten_service.py`, and `meta_media_service.py`. The Flask application coordinates processing, while OpenCV and Shapely help turn image detections into structured geometry. The browser frontend uses Three.js to render and interact with the scene.

## 🧩 How the System Works

```text
Floor-plan image
      ↓
Flask upload and job handling
      ↓
Meta SAM 3.1 segmentation + OpenCV image processing
      ↓
Shapely geometry and structured scene data
      ↓
Muse Spark scene understanding and room labels
      ↓
Three.js 3D viewer, editor, and navigation tools
```

The exact live-model steps depend on the configured API access and runtime mode. OpenCV fallback and prepared scenes support development and demonstrations when live inference is unavailable.

## 🎬 Prepared Demo Scenes

The **Meta AI Drafts** are saved scenes that load immediately without making a live model request. They make the project easy to explore during a presentation and provide a reliable offline demonstration. Uploaded plans follow the configured processing pipeline.

## 🧰 Technology Stack

| Area | Tools |
| --- | --- |
| Backend and API | Python, Flask |
| AI models | Meta SAM 3.1, Muse Spark; optional Muse Image and Muse Voice |
| Image processing | OpenCV, NumPy, Pillow |
| Geometry | Shapely |
| Interactive visualization | Three.js, JavaScript, HTML, CSS |
| Validation and tests | JSON Schema, pytest |

## 🚀 Installation and Setup

### Requirements

- Python 3.12 or newer
- Git
- A modern web browser
- Meta model API access for live inference (optional for prepared demos and local/mock mode)

### Windows PowerShell

```powershell
git clone https://github.com/tanmaysandhu55/Meta-Global-hackthon-Project.git
cd Meta-Global-hackthon-Project
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS or Linux

```sh
git clone https://github.com/tanmaysandhu55/Meta-Global-hackthon-Project.git
cd Meta-Global-hackthon-Project
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

### Configure and Run

Open `.env` and add the model credentials and model identifiers available to your account. Keep real keys in `.env`; do not commit that file. The checked-in `.env.example` contains placeholders.

Start the app:

```powershell
# Windows
.\.venv\Scripts\python.exe app.py
```

```sh
# macOS or Linux
.venv/bin/python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000). Without API credentials, prepared scenes remain available; live model features require valid credentials and supported model access.

## ✅ Tests

Run the automated tests from the project directory:

```sh
python -m pytest -q
```

The tests use mocked provider responses and do not require real API keys or live network calls.

## ⚠️ Limitations

Results depend on the clarity and style of the source drawing. High-contrast plans with clear boundaries generally work best. Detected geometry, scale, room areas, doors, and windows are estimates and may need correction in the review tools. FloorPlan3D is a visualization prototype; its output is not for construction, safety, evacuation planning, or code-compliance decisions.

## 👋 About

Built by **Tanmay Sandhu** for the **Meta Global AI Developer Hackathon**. Feedback and careful review of generated scenes are welcome.
