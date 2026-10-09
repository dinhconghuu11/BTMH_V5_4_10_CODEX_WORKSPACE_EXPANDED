# CampusFace Professional V9 Dynamic UI

- Replaced the dashboard hero block with a fully isolated `cfv9-*` component so legacy CSS cannot silently override the new design.
- Added real-time animated canvas particles, connecting data lines, moving wave fields, rotating HUD rings, scan line, pulsing scan corners and floating FaceID / Check-in nodes.
- Added a visible `V9 DYNAMIC UI` build marker on the hero to make stale UI immediately obvious.
- Added cache-control headers for `/` and `/static/*` so browser cache cannot keep old dashboard assets after an upgrade.
- Added a safe stale CampusFace server guard on port 8100. It only stops an existing CampusFace Python process; unrelated processes are not terminated.
- Startup opens `http://127.0.0.1:8100/?ui=v9` to make the new launch visually and diagnostically distinct.
- Core version: `1.26.0-v1-face-pro-v9`.
