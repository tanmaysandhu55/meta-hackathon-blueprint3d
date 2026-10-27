# FloorPlan3D demo script

## Before the presentation

- Start the Flask app and open the local page.
- Confirm **Load Hackathon Demo Plan** works while offline.
- Keep the sample loaded as the fallback. Live processing depends on valid provider keys and an available endpoint.
- Do not show `.env` or API key values on screen.

## Three-minute walkthrough

**0:00–0:20 — Introduce the goal**

“FloorPlan3D takes a 2D plan and turns it into a structured scene that a browser can explore in 3D. The prepared example lets me show the full viewer without relying on a live model call.”

**0:20–0:45 — Load the prepared sample**

Choose **Load Hackathon Demo Plan**. Point out that the 3D viewer, room labels, and prepared scene data load locally. Be clear that this is prepared example output, not a fresh SAM result.

**0:45–1:20 — Explore and verify the map**

Orbit the building, switch to top-down, toggle cutaway, focus a room from **Find and Route**, and click a room. If the prepared sample has a connected pair available, show a door-based route. Explain that the viewer uses meter coordinates from `scene.json`; the click panel shows the room’s label, type, and estimated area.

**1:20–1:50 — Correct an outline**

Click a room, choose **Edit room outline**, and open the 2D tab. Drag a cyan vertex to correct an estimated boundary, then use **Undo** to show that corrections are reversible. Finish and explain that the corrected scene is the one exported.

**1:50–2:15 — Ask the map**

Ask “Where is the Computer Lab?” Point out the provider label: it identifies Muse Spark through Modal or the offline scene lookup, so a prepared/lookup answer is not presented as a model answer.

**2:15–2:35 — Show the 2D and structured views**

Open the 2D overlay tab, then the `scene.json` tab. Explain that the scene contract keeps geometry and labels separate from the renderer.

**2:35–2:50 — Export**

Download the GLB and explain that it can be opened in a compatible 3D viewer. Avoid claiming it is a construction-ready BIM model.

**2:50–3:00 — State the limits clearly**

“The live upload path segments uploaded plans with SAM and can classify rooms when the optional labeler is configured. Review scale and room geometry before relying on measurements. Multi-floor alignment is estimated and needs verification.”

For a building with actual per-floor drawings, select the images together in ground-to-top order and choose **Process selected plans as stories**. The app aligns detected stair/elevator regions when possible. Check each story against its source drawing and verify alignment; the prepared two-story demo is illustrative and duplicates the sample layout.

## Likely issues and recovery

1. **No API keys or endpoint yet:** use the prepared sample. The UI should say **Offline demo mode** and disable live processing.
2. **Provider is unavailable or credentials are wrong:** use the prepared sample. Live processing reports a job failure; do not retry repeatedly during the presentation.
3. **A plan produces no rooms:** use the prepared sample and describe the live result as a segmentation limitation. Try a higher-contrast plan after the demo.
4. **Automatic scale cannot find doors:** the scene falls back to the selected meters-per-pixel scale and adds a warning. Use a plan with a known measurement or turn off automatic scale and set the slider.
5. **The browser or CDN cannot load Three.js/Tailwind:** keep the page already loaded before presenting and use a network connection that can reach the pinned CDN assets.

## Claims to keep precise

- The offline sample is precomputed and works without keys.
- The offline scene assistant is a deterministic lookup. Only a provider-labeled response from Muse Spark is a Muse Spark answer.
- Multi-floor image alignment is an estimate based on connector-room outlines or plan centers and needs visual confirmation.
- The map quality card reports structural checks, not measured model accuracy.
- Live segmentation is an external-service path; a configured flag does not guarantee provider reachability.
- Room classification may be generic when optional classification endpoints are unavailable.
- Scale, room boundaries, doors, and windows are estimates. This prototype is for visualization, not construction or safety decisions.
