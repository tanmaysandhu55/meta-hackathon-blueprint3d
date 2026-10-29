# FloorPlan3D demo

## Rehearsal

Start the Flask app and open the local page. Follow the sidebar's **Quick judge walkthrough**: load **Hackathon Demo Plan**, compare the 2D detections, run **AI plan review** and **Summarize building**, then ask “Route from East Lobby to Computer Lab.” The assistant resolves the named rooms from the scene and draws a route through the existing door graph. Load **Two-Story Demo** to show the floor selector, stairs, cross-floor route, area summary, and exports. These additions work without a key; when Baseten is configured, review/summary wording can use Muse Spark grounded in the same scene data. The review buttons can open the 2D overlay or select a room outline for manual correction.

Before presenting, run `python scripts/evaluate_local_segmentation.py` to check the bundled sample against coarse offline regression guardrails. It does not establish accuracy on arbitrary uploaded plans.

For an uploaded-plan demo, use a clean, high-contrast plan. Without keys, segmentation uses local OpenCV heuristics and room labels remain generic. A Baseten key enables Muse Spark Open labels and map answers. A separate Meta key enables SAM 3.1; failed SAM concepts fall back to OpenCV. Do not describe prepared demos or local fallback output as model output.

## Meta model setup

Set `BASETEN_API_KEY` to the key from your Baseten email and keep `BASETEN_API_BASE_URL` and `BASETEN_MUSE_MODEL` from `.env.example`, then restart. This key enables Muse Spark Open labels and scene-grounded map answers. SAM, Muse Image, and Voice Transcribe need a separate Meta Model API key; without it, local OpenCV and offline map lookup still work.

## Limitations

Heuristic boundaries work best on clean, high-contrast drawings. Open wall gaps, text, shadows, furniture, doors and windows can affect detection. Dimensions, areas, routes and multi-floor alignment are estimates. Verify against known measurements. This prototype is for visualization only, not construction or safety decisions.
