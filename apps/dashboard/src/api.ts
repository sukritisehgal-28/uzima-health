export const ORCH = import.meta.env.VITE_ORCHESTRATOR_URL ?? "http://localhost:8000";
export const WS = import.meta.env.VITE_COLLECTOR_WS ?? "ws://localhost:8003/stream";
// CARTO Positron (free, no key, light): state borders and city names. Set VITE_MAP_STYLE to the AWS Location style URL when USE_AWS=1.
export const MAP_STYLE = import.meta.env.VITE_MAP_STYLE ?? "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

export type Transport = { est_ground_min: number; est_air_min: number; recommended_mode: "ground" | "air"; tier: string };
export type Agent = { agent_id: string; hospital_id: string; hospital: string; lat: number; lng: number; live: boolean; transport: Transport };
export type Card = Agent & { status: string; ready_in_min?: number | null; decline_reason?: string | null; treatment_start_min?: number | null; last_line?: string; source?: "live" | "simulated"; error?: string };
/** Transfer ticket created on Connect: the patient's pass for the transfer (web page + optional Apple Wallet). Its QR code opens the encrypted record. */
export type Ticket = {
  id: string;
  code: string;              // short human code, e.g. "UZ-7K4Q2M"
  url: string;               // web ticket page (public https when a tunnel is set)
  wallet_url: string | null; // Apple Wallet .pkpass, or null when no Apple signing certificate is configured
  from: { name: string; city: string };
  to: { name: string; city: string };
  patient: string;           // "62-year-old male"
  condition: string;         // "Heart attack (STEMI)"
  mode: "ground" | "air";
  travel_min: number;
  eta: string;               // ISO datetime of expected arrival
  ready_in_min: number | null;
  treatment_in_min: number | null;
  insurance: string;         // "Mississippi Medicaid (offline mock) · active"
  expires: string;           // ISO datetime, 24 h
};
export type Twin = { shlink: string; hospital: string; insurance?: { payer: string; source: string }; ticket?: Ticket };

export async function getHealth() {   // which integrations are real right now (twilio: "live" | "mock")
  return (await fetch(`${ORCH}/health`)).json();
}
export async function getCenters() {
  return (await fetch(`${ORCH}/centers`)).json();
}
export async function startTransfer(specialty: string, window_min?: number) {
  // fictional demo patients: a 62-year-old man; an 8-year-old for pediatric trauma; a 28-year-old woman for childbirth
  const child = specialty === "trauma_pediatric", birth = specialty === "childbirth";
  const body = { age: child ? 8 : birth ? 28 : 62, sex: birth ? "Female" : "Male", is_pediatric: child, specialty, condition: LABEL[specialty],
                 onset_or_last_known_well: new Date(Date.now() - 50 * 60_000).toISOString(),   // fictional onset 50 min before the search
                 key_scores: {}, window_min };
  const r = await fetch(`${ORCH}/transfers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ transfer_id: string; agents: Agent[] }>;
}
export async function getStatus(tid: string) {
  return (await fetch(`${ORCH}/transfers/${tid}`)).json();
}
export async function accept(tid: string, hospital_id?: string) {
  const r = await fetch(`${ORCH}/transfers/${tid}/accept`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hospital_id, accepting_physician: "Dr. Accepting (demo)" }) });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ accepted: string; treatment_start_min?: number | null; twin?: Twin; bridge?: { mode: string; status: string } }>;
}
export const LABEL: Record<string, string> = {
  cardiac_icu: "Heart attack (STEMI)", stroke_thrombectomy: "Stroke, large-vessel", trauma_adult: "Severe trauma",
  trauma_burn: "Burn", trauma_pediatric: "Pediatric trauma", childbirth: "High-risk childbirth",
};
