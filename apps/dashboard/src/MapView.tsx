import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MAP_STYLE, type Card } from "./api";

// Status colors always come with a word (on the pin label and in the legend).
// color = dot / swatch fill, text = the same status as text on white (darker, for contrast), line = the line from the ER.
export const STATUS: Record<string, { color: string; text: string; line: string; label: string }> = {
  calling: { color: "#F2B35B", text: "#A86A06", line: "#F2B35B", label: "Calling" },
  callback_requested: { color: "#F2B35B", text: "#A86A06", line: "#F2B35B", label: "Call back in 5 min" },
  available: { color: "#5BD18B", text: "#1E8A4C", line: "#5BD18B", label: "Available" },
  declined: { color: "#EE7B6B", text: "#C2412F", line: "#EE7B6B", label: "Declined" },
  no_answer: { color: "#A3A6AD", text: "#6B6F77", line: "#C9CBD0", label: "No answer" },
  held: { color: "#5BD18B", text: "#1E8A4C", line: "#1E8A4C", label: "Held" },
  accepted: { color: "#5BD18B", text: "#1E8A4C", line: "#1E8A4C", label: "Accepted" },
  released: { color: "#C9CBD0", text: "#6B6F77", line: "#C9CBD0", label: "Released" },
};
const PRIORITY: Record<string, number> = { accepted: 0, held: 0, available: 1, callback_requested: 2, declined: 3, calling: 4, no_answer: 5, released: 6 };
const LEGEND = ["calling", "available", "declined", "no_answer", "released", "accepted"];
const RING_PX = 34;   // same-city hospitals (Jackson has four) sit on a ring this far from the true point

type Sending = { lat: number; lng: number; name: string; short_name?: string };
type Placement = { dx: number; dy: number; side: "top" | "bottom" | "left" | "right" };

/** Hospitals within ~0.2° share a city: spread them on a ring and point each label outward so labels don't collide. */
function place(cards: Card[]): Map<string, Placement> {
  const groups: { lat: number; lng: number; items: Card[] }[] = [];
  for (const c of cards) {
    const g = groups.find((x) => Math.abs(x.lat - c.lat) < 0.2 && Math.abs(x.lng - c.lng) < 0.2);
    g ? g.items.push(c) : groups.push({ lat: c.lat, lng: c.lng, items: [c] });
  }
  const out = new Map<string, Placement>();
  for (const g of groups) {
    g.items.forEach((c, i) => {
      if (g.items.length === 1) return out.set(c.agent_id, { dx: 0, dy: 0, side: "top" });
      const a = (2 * Math.PI * i) / g.items.length - Math.PI / 2;
      const dx = Math.round(RING_PX * Math.cos(a)), dy = Math.round(RING_PX * Math.sin(a));
      out.set(c.agent_id, { dx, dy, side: Math.abs(Math.cos(a)) > 0.7 ? (dx < 0 ? "left" : "right") : dy < 0 ? "top" : "bottom" });
    });
  }
  return out;
}

function statusLine(c: Card): string {
  const s = STATUS[c.status]?.label ?? c.status;
  if (["available", "accepted", "held"].includes(c.status) && c.ready_in_min != null) return `${s} · ready in ${c.ready_in_min} min`;
  if (c.status === "declined" && c.decline_reason) return `${s} · ${c.decline_reason}`;
  if (c.status === "calling") return "Calling…";
  return s;
}

function markerEl(c: Card, name: string): { root: HTMLElement; label: HTMLElement } {
  const s = STATUS[c.status] ?? STATUS.no_answer;
  const root = document.createElement("div");
  root.className = "mp-marker";
  const dot = document.createElement("div");
  dot.className = ["mp-dot", c.live ? "live" : "", ["calling", "callback_requested"].includes(c.status) ? "mp-pulse" : "", c.status].join(" ");
  dot.style.background = s.color;
  dot.textContent = c.agent_id.replace("A", "");
  const label = document.createElement("div");
  label.className = "mp-label mp-top";
  label.style.borderLeftColor = s.color;
  const t = document.createElement("div"); t.className = "t";
  const id = document.createElement("span"); id.className = "id"; id.textContent = c.agent_id;
  t.append(id);
  if (c.live) { const tag = document.createElement("span"); tag.className = "live"; tag.textContent = "live"; t.append(tag); }
  t.append(document.createTextNode(name));
  const st = document.createElement("div"); st.className = "s"; st.style.color = s.text; st.textContent = statusLine(c);
  label.append(t, st);
  root.append(dot, label);
  return { root, label };
}

type Box = { x: number; y: number; w: number; h: number };
const overlaps = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export default function MapView({ sending, cards, names, focusKey, searching }:
  { sending?: Sending; cards: Card[]; names: Record<string, string>; focusKey?: string; searching: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const legend = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const placed = useRef<{ card: Card; p: Placement; marker: maplibregl.Marker; label: HTMLElement }[]>([]);
  const sendingRef = useRef<Sending | undefined>(sending);
  const ready = useRef(false);
  sendingRef.current = sending;

  /** Ring offsets are in pixels, so each shown position (and its line end) is recomputed on every zoom. */
  const reposition = () => {
    const m = map.current, s = sendingRef.current;
    if (!m || !s || !ready.current) return;
    const features = placed.current.map(({ card, p, marker }) => {
      const base = m.project([card.lng, card.lat]);
      const at = m.unproject([base.x + p.dx, base.y + p.dy]);
      marker.setLngLat(at);
      return { type: "Feature" as const, properties: { status: card.status, color: (STATUS[card.status] ?? STATUS.no_answer).line },
        geometry: { type: "LineString" as const, coordinates: [[s.lng, s.lat], [at.lng, at.lat]] } };
    });
    (m.getSource("links") as maplibregl.GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features });
    layoutLabels();
  };

  /** Label collision avoidance: most important statuses first; each label tries its preferred side, then the others,
   *  and is hidden (pin and number stay) if no side is free. Runs after every zoom and redraw. */
  /** Floating cards over the map (marked data-map-overlay): labels avoid them and the fit keeps pins clear of them. */
  const overlays = (): Box[] => {
    const c = el.current;
    if (!c?.parentElement) return [];
    const base = c.getBoundingClientRect();
    return [...c.parentElement.querySelectorAll<HTMLElement>("[data-map-overlay]")].map((o) => {
      const r = o.getBoundingClientRect();
      return { x: r.left - base.left - 6, y: r.top - base.top - 6, w: r.width + 12, h: r.height + 12 };
    });
  };

  const layoutLabels = () => {
    const m = map.current, s = sendingRef.current;
    if (!m || !s) return;
    const { clientWidth: W, clientHeight: H } = m.getContainer();
    const er = m.project([s.lng, s.lat]);
    const lg = legend.current;
    const legendBox = lg ? { x: 0, y: lg.offsetTop - 6, w: lg.offsetLeft + lg.offsetWidth + 6, h: H - lg.offsetTop + 6 } : { x: 0, y: H - 44, w: 640, h: 44 };
    const taken: Box[] = [{ x: er.x - 16, y: er.y - 16, w: 32, h: 32 }, legendBox, ...overlays()];
    const pts = placed.current.map((e) => m.project(e.marker.getLngLat()));
    pts.forEach((pt) => taken.push({ x: pt.x - 16, y: pt.y - 16, w: 32, h: 32 }));
    const order = placed.current.map((e, i) => ({ e, pt: pts[i] }))
      .sort((a, b) => (PRIORITY[a.e.card.status] ?? 9) - (PRIORITY[b.e.card.status] ?? 9));
    for (const { e, pt } of order) {
      const el = e.label;
      el.classList.remove("hidden-label");
      const w = el.offsetWidth, h = el.offsetHeight, g = 18;
      const sides: Placement["side"][] = [e.p.side, ...(["top", "right", "left", "bottom"] as const).filter((x) => x !== e.p.side)];
      let chosen: Placement["side"] | null = null;
      for (const side of sides) {
        const box = side === "top" ? { x: pt.x - w / 2, y: pt.y - g - h, w, h } : side === "bottom" ? { x: pt.x - w / 2, y: pt.y + g, w, h }
          : side === "left" ? { x: pt.x - g - w, y: pt.y - h / 2, w, h } : { x: pt.x + g, y: pt.y - h / 2, w, h };
        const inside = box.x > 4 && box.y > 4 && box.x + box.w < W - 50 && box.y + box.h < H - 4;
        if (inside && !taken.some((t) => overlaps(t, box))) { chosen = side; taken.push(box); break; }
      }
      el.className = `mp-label mp-${chosen ?? "top"}${chosen ? "" : " hidden-label"}`;
    }
  };

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = new maplibregl.Map({ container: el.current, style: MAP_STYLE, center: [-90.3, 33.4], zoom: 6, attributionControl: { compact: true } });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.on("load", () => {
      m.addSource("links", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "links-done", type: "line", source: "links", filter: ["!", ["in", ["get", "status"], ["literal", ["calling", "callback_requested"]]]],
        layout: { "line-cap": "round" },
        paint: { "line-color": ["get", "color"], "line-width": ["case", ["==", ["get", "status"], "accepted"], 3, 1.5],
                 "line-opacity": ["case", ["==", ["get", "status"], "accepted"], 1, ["in", ["get", "status"], ["literal", ["released", "no_answer"]]], 0.9, 0.85] } });
      m.addLayer({ id: "links-calling", type: "line", source: "links", filter: ["in", ["get", "status"], ["literal", ["calling", "callback_requested"]]],
        paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-dasharray": [3, 3], "line-opacity": 0.9 } });
      ready.current = true;
      m.fire("mp:ready");
    });
    m.on("zoom", reposition);
    m.on("resize", layoutLabels);
    map.current = m;
    const ro = new ResizeObserver(() => m.resize());   // the grid finishes layout after the map mounts
    ro.observe(el.current);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !sending) return;
    const draw = () => {
      markers.current.forEach((x) => x.remove());
      placed.current = [];
      const er = document.createElement("div");
      er.className = `mp-er${searching ? " searching" : ""}`;
      er.textContent = "ER";
      markers.current = [new maplibregl.Marker({ element: er }).setLngLat([sending.lng, sending.lat])
        .setPopup(new maplibregl.Popup({ offset: 22 }).setText(`${sending.name}\nSending hospital`)).addTo(m)];
      const where = place(cards);
      for (const c of cards) {
        const p = where.get(c.agent_id) ?? { dx: 0, dy: 0, side: "top" as const };
        const { root, label } = markerEl(c, names[c.hospital_id] ?? c.hospital);
        const mode = c.transport.recommended_mode, mins = mode === "air" ? c.transport.est_air_min : c.transport.est_ground_min;
        const details = `${c.hospital}\n${statusLine(c)}\n${mode === "air" ? "Air" : "Ground"} ${mins} min · ${c.transport.tier.replace(/_/g, " ")}` +
          `${c.treatment_start_min != null ? `\nTreatment could start in ~${c.treatment_start_min} min` : ""}${c.last_line ? `\n“${c.last_line}”` : ""}`;
        const mk = new maplibregl.Marker({ element: root }).setLngLat([c.lng, c.lat])
          .setPopup(new maplibregl.Popup({ offset: 16, maxWidth: "300px" }).setText(details)).addTo(m);
        markers.current.push(mk);
        placed.current.push({ card: c, p, marker: mk, label });
      }
      reposition();
    };
    ready.current ? draw() : m.once("mp:ready", draw);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sending, cards, names, searching]);

  // Fit to the sending hospital and every hospital being called, once per transfer.
  useEffect(() => {
    const m = map.current;
    if (!m || !sending) return;
    const fit = () => {
      if (!cards.length) return m.jumpTo({ center: [sending.lng - 0.6, sending.lat - 0.2], zoom: 6.2 });
      const b = new maplibregl.LngLatBounds([sending.lng, sending.lat], [sending.lng, sending.lat]);
      cards.forEach((c) => b.extend([c.lng, c.lat]));
      const H = m.getContainer().clientHeight;
      const top = Math.max(90, ...overlays().filter((o) => o.y < H / 3).map((o) => o.y + o.h + 12));
      m.fitBounds(b, { padding: { top: Math.min(top, H / 2), left: 120, right: 150, bottom: 80 }, maxZoom: 8, duration: 0 });
    };
    ready.current ? fit() : m.once("mp:ready", fit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sending, focusKey]);

  return (
    <div className="relative h-full w-full">
      <div ref={el} className="h-full w-full" />
      <div ref={legend} className="absolute bottom-3 left-3 flex max-w-[calc(100%-7rem)] flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-ink-line bg-ink-panel px-3 py-1.5 text-[11px] text-ink-muted shadow-xs">
        <span className="flex items-center gap-1.5 whitespace-nowrap"><span className="inline-block h-2.5 w-2.5 rounded-[3px] bg-ink-text" />Sending ER</span>
        {LEGEND.map((k) => (
          <span key={k} className="flex items-center gap-1.5 whitespace-nowrap">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS[k].color }} />{STATUS[k].label}
          </span>
        ))}
      </div>
    </div>
  );
}
