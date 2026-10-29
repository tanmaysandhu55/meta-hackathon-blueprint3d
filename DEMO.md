# FloorPlan3D demo

## Rehearsal

Start the Flask app and open the local page. Follow the sidebar's **Quick judge walkthrough**: load **Hackathon Demo Plan**, compare the 2D detections, inspect the structural review checklist, then load **Two-Story Demo** and show the floor selector, stairs, route, area summary, and exports. Both prepared examples work without a key. The review buttons can open the 2D overlay or select a room outline for manual correction.

Before presenting, run `python scripts/evaluate_local_segmentation.py` to check the bundled sample against coarse offline regression guardrails. It does not establish accuracy on arbitrary uploaded plans.

For an uploaded-plan demo, use a clean, high-contrast plan. Without keys, segmentation uses local OpenCV heuristics and room labels remain generic. A Baseten key enables Muse Spark Open labels and map answers. A separate Meta key enables SAM 3.1; failed SAM concepts fall back to OpenCV. Do not describe prepared demos or local fallback output as model output.

## Meta model setup

Set `BASETEN_API_KEY` to the key from your Baseten email and keep `BASETEN_API_BASE_URL` and `BASETEN_MUSE_MODEL` from `.env.example`, then restart. This key enables Muse Spark Open labels and scene-grounded map answers. SAM, Muse Image, and Voice Transcribe need a separate Meta Model API key; without it, local OpenCV and offline map lookup still work.

## Limitations

Heuristic boundaries work best on clean, high-contrast drawings. Open wall gaps, text, shadows, furniture, doors and windows can affect detection. Dimensions, areas, routes and multi-floor alignment are estimates. Verify against known measurements. This prototype is for visualization only, not construction or safety decisions.
