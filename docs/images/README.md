# Synthetic product-tour imagery

These PNGs are reproducible documentation captures from the Playwright fixture
at `frontend/e2e/fixtures/product-tour.html`. They use the repository's real
React components and in-memory synthetic transports only: no provider history,
local files, credentials, model runtime, GPU, or network service is read.

Regenerate with:

```powershell
cd frontend
$env:PE_CAPTURE_PRODUCT_TOUR='1'
npx playwright test --config=playwright.config.ts product-tour-screenshots.spec.ts
```

The `live-mini-window.png` frame is the actual `LiveMiniWindow` route. The
`session-radar.png` frame is a separate `SessionRadarCard` dashboard surface
with twelve deterministic synthetic readings. The `ensemble-overlay.png`
frame is the actual `ModelEnsembleOverlay` live-watch surface, populated from
the repository's synthetic checkpoint receipt; its summary reports the fixed
20-axis model-ensemble contract (`1/20` measured in this receipt). These are
separate app surfaces, not a combined mock.
