# FloorPlan3D demo

## Rehearsal

Start the Flask app and open the local page. Follow the sidebar's **Quick judge walkthrough**: load **Hackathon Demo Plan**, compare the 2D detections, inspect the structural review checklist, then load **Two-Story Demo** and show the floor selector, stairs, route, area summary, and exports. Both prepared examples work without a key. The review buttons can open the 2D overlay or select a room outline for manual correction.

Before presenting, run `python scripts/evaluate_local_segmentation.py` to check the bundled sample against coarse offline regression guardrails. It does not establish accuracy on arbitrary uploaded plans.

For an uploaded-plan demo, use a clean, high-contrast plan. Without an API key, segmentation uses local OpenCV heuristics and room labels remain generic. With a key, SAM 3.1 segments the image and Muse Spark can suggest room labels; failed SAM concepts fall back to OpenCV. Do not describe prepared demos or local fallback output as model output.

## Meta model setup

When ready, set `META_API_KEY` in `.env`, keep the model IDs and `META_API_BASE_URL` from `.env.example`, then restart the app. One Meta key enables SAM segmentation, Muse Spark room labels, Muse Image draft generation, and Muse Voice transcription, subject to account access. Live model access remains unverified until tested with your account.

## Limitations

Heuristic boundaries work best on clean, high-contrast drawings. Open wall gaps, text, shadows, furniture, doors and windows can affect detection. Dimensions, areas, routes and multi-floor alignment are estimates. Verify against known measurements. This prototype is for visualization only, not construction or safety decisions.
