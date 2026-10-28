# FloorPlan3D demo

## Rehearsal

Start the Flask app and open the local page. Follow the sidebar's **Quick judge walkthrough**: load **Hackathon Demo Plan**, compare the 2D detections, inspect the structural review checklist, then load **Two-Story Demo** and show the floor selector, stairs, route, area summary, and exports. Both prepared examples work without a key. The review buttons can open the 2D overlay or select a room outline for manual correction.

Before presenting, run `python scripts/evaluate_local_segmentation.py` to check the bundled sample against coarse offline regression guardrails. It does not establish accuracy on arbitrary uploaded plans.

For an uploaded-plan demo, use a clean, high-contrast plan. Explain that segmentation uses local OpenCV heuristics. Without Llama settings, room labels remain generic and a warning appears. Do not describe prepared or generic output as model output.

## Optional Llama labels

When ready, set LLAMA_API_KEY and the exact LLAMA_VISION_MODEL from the API dashboard in .env, keep LLAMA_API_BASE_URL at `https://api.meta.ai/v1` unless your account dashboard specifies another URL, and restart the app. Segmentation does not need this key. Model access and response compatibility remain unverified until tested with a real account.

## Limitations

Heuristic boundaries work best on clean, high-contrast drawings. Open wall gaps, text, shadows, furniture, doors and windows can affect detection. Dimensions, areas, routes and multi-floor alignment are estimates. Verify against known measurements. This prototype is for visualization only, not construction or safety decisions.
