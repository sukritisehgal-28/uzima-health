# Dashboard (React + Vite + Tailwind + MapLibre)

    cd apps/dashboard && npm install && npm run dev

- Subscribes to the collector at `VITE_COLLECTOR_WS` (default `ws://localhost:8003/stream`) and renders the four call events + full results.
- Map: MapLibre with AWS Location Service tiles; sending hospital in the center, one line per agent (dashed yellow while calling, green available, red declined, grey no answer, thick glow on accept).
- Two clocks: swarm elapsed vs "one by one: still on call N of 10" (assumes ~90 s per sequential call).
- Every status is a color + a word; the "responses are simulated" label stays on screen.
