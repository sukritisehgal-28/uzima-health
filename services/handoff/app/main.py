"""Patient handoff twin (FR-15..17).

An IPS-shaped FHIR document bundle (HL7 International Patient Summary: medications, allergies, problem list
+ a custom Transfer section with every call, the plan and the ground-vs-air rationale), plus a FHIR Coverage
resource from a real-time eligibility check (X12 270/271 via Stedi; the demo uses Stedi's free mock requests).

Delivered as a SMART Health Link (HL7 IG): the bundle is encrypted as a JWE with alg "dir" / enc "A256GCM",
the link carries the manifest URL (>=256 bits of entropy) and the 32-byte key, and "exp" makes it stale after
24 hours. Our links carry no passcode: the ticket's QR code is the key, like the patient's own wallet pass (flag "P"
is still supported for links made with a passcode). Any SMART Health Links viewer can open it. Nothing is stored in
the clear.

GET /view is a built-in viewer: it reads the link from the URL fragment (never sent to the server), fetches the
encrypted file and decrypts it in the browser. For phones, HANDOFF_PUBLIC_URL must be an
https tunnel to this service (browsers only decrypt on https or localhost).

Transfer ticket: on acceptance the record also gets a boarding-pass style ticket that travels with the patient
(GET /tickets/{id}, and GET /tickets/{id}.pkpass for Apple Wallet once a Pass Type ID certificate is configured).
Its QR code is the SMART Health Link; the receiving team scans it on arrival to open the full record. The ticket
keeps a copy of the link for 24 hours like a paper ticket would, so whoever holds the ticket can open the record.
"""
import base64
import hashlib
import html
import io
import json
import os
import secrets
import struct
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import segno
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from services.shared import config
from services.shared.schemas import AgentResult, Case, InsuranceCheck, TransportEstimate, TwinRequest

app = FastAPI(title="Project Uzima handoff twin")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])   # any SHL viewer may fetch
STEDI = "https://healthcare.us.stedi.com/2024-04-01/change/medicalnetwork/eligibility/v3"
# Address that goes into links: a public https tunnel to port 8004 on demo day. HANDOFF_URL stays the internal address.
BASE = (os.getenv("HANDOFF_PUBLIC_URL") or os.getenv("HANDOFF_URL", "http://localhost:8004")).rstrip("/")
_viewer = os.getenv("SHL_VIEWER_URL", "")
VIEWER = _viewer if _viewer and "shl-viewer.example" not in _viewer else f"{BASE}/view"   # empty or old placeholder = built-in
FHIR_JSON = "application/fhir+json;fhirVersion=4.0.1"
MAX_WRONG_PASSCODES = 10      # lifetime limit per link, so a 6-digit passcode can't be guessed (SHL spec)
VIEWER_HTML = (Path(__file__).parent / "viewer.html").read_text()
TICKET_HTML = Template((Path(__file__).parent / "ticket.html").read_text())
DATA = json.loads((Path(__file__).resolve().parents[3] / "data" / "hospitals.json").read_text())
PLACES = {h["id"]: h for h in [DATA["sending"], *DATA["centers"]]}
DEMO_PATIENTS = json.loads((Path(__file__).resolve().parents[3] / "data" / "demo_patients.json").read_text())   # fictional
CREW = {"ground": "Advanced life support (ALS) ground ambulance: paramedic and nurse",
        "air": "Critical care air transport: flight nurse and flight paramedic"}
TZ = ZoneInfo(os.getenv("DEMO_TZ", "America/Chicago"))   # every demo hospital is on Central time
_store: dict[str, dict] = {}   # twin_id -> {jwe, passcode, exp, tries_left}; DynamoDB in production
_tickets: dict[str, dict] = {}   # ticket_id -> {ticket, link, exp}


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def check_insurance(payer_id: str, member_id: str, first: str, last: str, dob: str) -> InsuranceCheck:
    """Stedi eligibility. With a TEST key only the documented mock member IDs work (free, no real payer)."""
    r = httpx.post(STEDI, headers={"Authorization": os.environ["STEDI_TEST_API_KEY"]},
                   json={"tradingPartnerServiceId": payer_id,
                         "provider": {"organizationName": "South Sunflower County Hospital", "npi": os.getenv("DEMO_NPI", "1999999984")},
                         "subscriber": {"memberId": member_id, "firstName": first, "lastName": last, "dateOfBirth": dob}}, timeout=30)
    r.raise_for_status()
    data = r.json()
    plan = (data.get("planInformation") or {}).get("planNumber") or (data.get("planStatus") or [{}])[0].get("planDetails")
    return InsuranceCheck(payer=payer_id, member_id_masked=f"***{member_id[-4:]}", active=True, plan=plan,
                          checked_at=datetime.now(timezone.utc))


def with_demo_details(case: Case) -> tuple[Case, list[str]]:
    """Fill empty handoff fields from the fictional demo patient for this case type. What the clinician gave always wins."""
    d = DEMO_PATIENTS.get(case.specialty.value, {})
    now = datetime.now(timezone.utc)
    clock = lambda minutes: (now - timedelta(minutes=minutes)).astimezone(TZ).strftime("%-I:%M %p %Z")
    fill = {"key_scores": d.get("key_scores"), "imaging_or_ecg": d.get("imaging_or_ecg"), "weight_kg": d.get("weight_kg"),
            "vitals": d.get("vitals"), "labs": d.get("labs"),
            "treatment_given": [f"{t['what']}, {clock(t['min_ago'])}" for t in d.get("treatment_given", [])],
            "response_to_treatment": d.get("response_to_treatment"), "allergies": d.get("allergies"), "pending": d.get("pending"),
            "certification": d.get("certification"), "consent": d.get("consent")}
    updates = {k: v for k, v in fill.items() if v and not getattr(case, k)}
    if "vitals" in updates:
        updates["vitals_at"] = _iso(now - timedelta(minutes=d.get("vitals_min_ago", 5)))
    if case.sending_physician.startswith("["):
        updates["sending_physician"] = "Referring physician (demo)"
    return case.model_copy(update=updates), sorted(k for k in updates if k not in ("vitals_at", "sending_physician"))


def ips_bundle(case: Case, accepted_hospital_id: str, accepting_physician: str, transport: TransportEstimate,
               calls: list[AgentResult], insurance: Optional[InsuranceCheck], demo_details: Optional[list[str]] = None) -> dict:
    """IPS sections plus what EMTALA 42 CFR 489.24(e)(2)(iii) asks to travel with the patient: history, signs and symptoms,
    preliminary diagnosis, test results, treatment given, and the physician's certification or the patient's consent."""
    now = datetime.now(timezone.utc).isoformat()
    pid = "patient-1"
    subj = {"reference": f"Patient/{pid}"}
    entries: list[dict] = []
    refs: dict[str, list[dict]] = {"vital-signs": [], "laboratory": []}

    def obs(oid: str, category: str, name: str, value, at: Optional[str] = None) -> None:
        value_field = {"valueQuantity": {"value": value}} if isinstance(value, (int, float)) else {"valueString": str(value)}
        entries.append({"resource": {"resourceType": "Observation", "id": oid, "status": "final", "category": [{"text": category}],
                                     "subject": subj, "code": {"text": name}, **value_field, **({"effectiveDateTime": at} if at else {})}})
        refs.setdefault(category, []).append({"reference": f"Observation/{oid}"})

    def narrative(items: list[str]) -> dict:
        return {"status": "generated", "div": '<div xmlns="http://www.w3.org/1999/xhtml"><ul>'
                + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul></div>"}

    entries.append({"resource": {"resourceType": "Patient", "id": pid, "gender": case.sex.lower(),
                                 "extension": [{"url": "http://uzima.local/age-years", "valueInteger": case.age}]}})
    entries.append({"resource": {"resourceType": "Condition", "id": "cond-1", "subject": subj,
                                 "code": {"text": case.condition}, "onsetDateTime": case.onset_or_last_known_well}})
    for i, (k, v) in enumerate(case.key_scores.items(), start=1):
        obs(f"score-{i}", "score", k, v)
    for i, (k, v) in enumerate(case.vitals.items(), start=1):
        obs(f"vital-{i}", "vital-signs", k, v, case.vitals_at)
    if case.weight_kg:
        obs("weight", "vital-signs", "Body weight", f"{case.weight_kg:g} kg", case.vitals_at)
    for i, (k, v) in enumerate(case.labs.items(), start=1):
        obs(f"lab-{i}", "laboratory", k, v)
    med_refs, allergy_refs, result_refs = [], [], []
    if case.blood_thinners:
        entries.append({"resource": {"resourceType": "MedicationStatement", "id": "med-1", "status": "active",
                                     "subject": subj, "medicationCodeableConcept": {"text": case.blood_thinners}}})
        med_refs.append({"reference": "MedicationStatement/med-1"})
    if case.allergies:
        entries.append({"resource": {"resourceType": "AllergyIntolerance", "id": "allergy-1", "patient": subj, "code": {"text": case.allergies}}})
        allergy_refs.append({"reference": "AllergyIntolerance/allergy-1"})
    if case.imaging_or_ecg:
        entries.append({"resource": {"resourceType": "DiagnosticReport", "id": "dx-1", "status": "final",
                                     "subject": subj, "code": {"text": "ECG / imaging"}, "conclusion": case.imaging_or_ecg}})
        result_refs.append({"reference": "DiagnosticReport/dx-1"})
    if insurance:
        entries.append({"resource": {"resourceType": "Coverage", "id": "cov-1", "status": "active" if insurance.active else "cancelled",
                                     "beneficiary": subj, "payor": [{"display": insurance.payer}],
                                     "subscriberId": insurance.member_id_masked,
                                     "class": [{"type": {"text": "plan"}, "value": insurance.plan or "unknown"}]}})
    transfer = {"accepted_hospital_id": accepted_hospital_id, "accepting_physician": accepting_physician,
                "transport": transport.model_dump(), "rationale": (
                    f"{transport.recommended_mode} recommended: ground {transport.est_ground_min} min, "
                    f"air {transport.est_air_min} min, tier {transport.tier}"),
                "crew": CREW.get(transport.recommended_mode), "tz": getattr(TZ, "key", None),
                "treatment_given": case.treatment_given, "response_to_treatment": case.response_to_treatment, "pending": case.pending,
                "certification": {"by": case.sending_physician, "summary": case.certification} if case.certification else None,
                "consent": case.consent, "demo_details": demo_details or [],
                "calls": [c.model_dump(mode="json") for c in calls]}
    empty = lambda why: {"emptyReason": {"text": why}}
    composition = {"resourceType": "Composition", "id": "comp-1", "status": "final",
                   "type": {"coding": [{"system": "http://loinc.org", "code": "60591-5", "display": "Patient summary Document"}]},
                   "subject": subj, "date": now, "title": "Project Uzima handoff twin",
                   "author": [{"display": case.sending_physician}],
                   "section": [
                       {"title": "Medication Summary", **({"entry": med_refs} if med_refs else empty("none reported at transfer"))},
                       {"title": "Allergies and Intolerances", **({"entry": allergy_refs} if allergy_refs else empty("unknown at transfer"))},
                       {"title": "Problem List", "entry": [{"reference": "Condition/cond-1"}]},
                       {"title": "Vital Signs", **({"entry": refs["vital-signs"]} if refs["vital-signs"] else empty("not recorded"))},
                       {"title": "Results", **({"entry": result_refs + refs["laboratory"]} if result_refs or refs["laboratory"] else empty("none yet"))},
                       {"title": "Treatment Given", **({"text": narrative(case.treatment_given)} if case.treatment_given else empty("none recorded"))},
                       {"title": "Plan of Care", **({"text": narrative(case.pending)} if case.pending else empty("none recorded"))},
                       {"title": "Transfer", "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">" + json.dumps(transfer) + "</div>"}},
                   ]}
    entries.insert(0, {"resource": composition})
    return {"resourceType": "Bundle", "type": "document", "timestamp": now, "entry": entries}


def make_shl(bundle: dict, passcode: Optional[str] = None, hours: int = 24) -> tuple[str, str]:
    """Encrypt the bundle as a JWE (dir / A256GCM) and build the SMART Health Link."""
    key, iv = secrets.token_bytes(32), secrets.token_bytes(12)
    header = b64url(json.dumps({"alg": "dir", "enc": "A256GCM", "cty": FHIR_JSON}).encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(bundle).encode(), header.encode())
    jwe = f"{header}..{b64url(iv)}.{b64url(ct[:-16])}.{b64url(ct[-16:])}"
    twin_id = secrets.token_urlsafe(32)                       # >= 256 bits of entropy in the manifest URL
    exp = int((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp())
    _store[twin_id] = {"jwe": jwe, "passcode": passcode, "exp": exp, "tries_left": MAX_WRONG_PASSCODES}
    payload = {"url": f"{BASE}/manifests/{twin_id}", "key": b64url(key), "exp": exp, **({"flag": "P"} if passcode else {}),
               "label": "Project Uzima handoff twin", "v": 1}
    return twin_id, f"{VIEWER}#shlink:/{b64url(json.dumps(payload).encode())}"


def decrypt_shl(jwe: str, key_b64url: str) -> dict:
    """Used by tests and the dashboard preview; a real viewer does the same per the SHL spec."""
    header, _, iv, ct, tag = jwe.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    key = base64.urlsafe_b64decode(pad(key_b64url))
    data = AESGCM(key).decrypt(base64.urlsafe_b64decode(pad(iv)), base64.urlsafe_b64decode(pad(ct)) + base64.urlsafe_b64decode(pad(tag)), header.encode())
    return json.loads(data)


class ManifestRequest(BaseModel):
    recipient: str
    passcode: Optional[str] = None


@app.post("/twins")
def build_twin(req: TwinRequest):
    insurance = None
    if req.insurance_test and config.has_stedi():
        try:
            insurance = check_insurance(**req.insurance_test)       # Stedi test key + documented mock member
        except Exception:
            insurance = None
    if insurance is None:                                       # offline mock so the demo never depends on it
        insurance = InsuranceCheck(payer="Mississippi Medicaid (offline mock)", member_id_masked="***0000", active=True,
                                   plan="demo", checked_at=datetime.now(timezone.utc), source="offline-mock")
    case, demo_details = with_demo_details(req.case)
    bundle = ips_bundle(case, req.accepted_hospital_id, req.accepting_physician, req.transport, req.calls, insurance, demo_details)
    twin_id, link = make_shl(bundle)                       # no passcode: the ticket's QR code is the key (24 h expiry)
    ticket = make_ticket(req, case, link, insurance, _store[twin_id]["exp"])
    # TODO: persist _store and _tickets to DynamoDB
    return {"twin_id": twin_id, "shlink": link, "insurance": insurance.model_dump(mode="json"),
            "sections": [s["title"] for s in bundle["entry"][0]["resource"]["section"]], "ticket": ticket}


# ---------------------------------------------------------------- transfer ticket (web + Apple Wallet)

def _iso(d: datetime) -> str:
    return d.replace(microsecond=0).isoformat()


def _city(place: dict) -> str:
    return ", ".join(x for x in (place.get("city"), place.get("state")) if x)


def _short(place: dict) -> str:
    return (place.get("short_name") or place.get("name") or "").split(",")[0]


def wallet_ready() -> bool:
    """Apple only installs passes signed with a Pass Type ID certificate (Apple Developer Program)."""
    return all(os.getenv(k) for k in ("APPLE_PASS_TYPE_ID", "APPLE_TEAM_ID", "APPLE_PASS_P12", "APPLE_WWDR_CERT"))


def make_ticket(req: TwinRequest, case: Case, link: str, insurance: InsuranceCheck, exp: int) -> dict:
    t = req.transport
    travel = t.est_ground_min if t.recommended_mode == "ground" else t.est_air_min
    chosen = next((c for c in req.calls if c.hospital_id == req.accepted_hospital_id), None)
    src, dst = PLACES.get(case.sending_hospital_id, {}), PLACES.get(req.accepted_hospital_id, {})
    tid = secrets.token_urlsafe(24)
    ticket = {
        "id": tid,
        "code": "UZ-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6)),
        "url": f"{BASE}/tickets/{tid}",
        "wallet_url": f"{BASE}/tickets/{tid}.pkpass" if wallet_ready() else None,
        "from": {"name": src.get("name", req.case.sending_hospital_id), "short": _short(src), "city": _city(src)},
        "to": {"name": dst.get("name") or (chosen.hospital if chosen else req.accepted_hospital_id), "short": _short(dst), "city": _city(dst)},
        "patient": f"{case.age}-year-old {case.sex.lower()}",
        "condition": case.condition,
        "allergies": case.allergies or "Not recorded",
        "crew": CREW.get(t.recommended_mode),
        "mode": t.recommended_mode,
        "travel_min": travel,
        "eta": _iso(datetime.now(timezone.utc) + timedelta(minutes=travel)),
        "ready_in_min": chosen.ready_in_min if chosen else None,
        "treatment_in_min": chosen.treatment_start_min if chosen else None,
        "insurance": f"{insurance.payer} · {'active' if insurance.active else 'not active'}",
        "expires": _iso(datetime.fromtimestamp(exp, timezone.utc)),
    }
    _tickets[tid] = {"ticket": ticket, "link": link, "exp": exp}
    return ticket


def _live_ticket(tid: str) -> dict:
    t = _tickets.get(tid)
    if not t or t["exp"] < datetime.now(timezone.utc).timestamp():
        raise HTTPException(404, "ticket not found or expired")
    return t


def _png(size: int) -> bytes:
    """Wallet icon: a gold ring on ink, drawn without an image library."""
    c, outer, inner = (size - 1) / 2, size * 0.36, size * 0.22
    rows = b"".join(b"\x00" + b"".join(bytes((240, 192, 106, 255)) if inner <= ((x - c) ** 2 + (y - c) ** 2) ** .5 <= outer
                                       else bytes((10, 11, 13, 255)) for x in range(size)) for y in range(size))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


ICONS = {"icon.png": _png(29), "icon@2x.png": _png(58), "icon@3x.png": _png(87)}


def pass_json(ticket: dict, link: str) -> dict:
    ready = ticket["ready_in_min"]
    return {
        "formatVersion": 1, "passTypeIdentifier": os.environ["APPLE_PASS_TYPE_ID"], "teamIdentifier": os.environ["APPLE_TEAM_ID"],
        "serialNumber": ticket["id"], "organizationName": "Project Uzima", "description": "Patient transfer ticket",
        "logoText": "Project Uzima", "sharingProhibited": True,
        "foregroundColor": "rgb(10, 11, 13)", "backgroundColor": "rgb(255, 255, 255)", "labelColor": "rgb(138, 93, 11)",
        "expirationDate": ticket["expires"], "relevantDate": ticket["eta"],
        "barcodes": [{"format": "PKBarcodeFormatQR", "message": link, "messageEncoding": "iso-8859-1", "altText": ticket["code"]}],
        "boardingPass": {
            "transitType": "PKTransitTypeGeneric",
            "headerFields": [{"key": "eta", "label": "ARRIVES", "value": ticket["eta"], "timeStyle": "PKDateStyleShort", "dateStyle": "PKDateStyleNone"}],
            "primaryFields": [{"key": "from", "label": ticket["from"]["short"].upper(), "value": ticket["from"]["city"].split(",")[0]},
                              {"key": "to", "label": ticket["to"]["short"].upper(), "value": ticket["to"]["city"].split(",")[0]}],
            "secondaryFields": [{"key": "patient", "label": "PATIENT", "value": ticket["patient"]},
                                {"key": "condition", "label": "CONDITION", "value": ticket["condition"]}],
            "auxiliaryFields": [{"key": "mode", "label": "TRANSPORT", "value": f"{ticket['mode'].capitalize()} · {ticket['travel_min']} min"},
                                {"key": "ready", "label": "TEAM READY", "value": f"{ready} min" if ready is not None else "confirm"},
                                {"key": "code", "label": "TICKET", "value": ticket["code"]}],
            "backFields": [
                {"key": "to_full", "label": "Receiving hospital", "value": f"{ticket['to']['name']}, {ticket['to']['city']}"},
                {"key": "from_full", "label": "Sending hospital", "value": f"{ticket['from']['name']}, {ticket['from']['city']}"},
                {"key": "allergies", "label": "Allergies", "value": ticket["allergies"]},
                {"key": "crew", "label": "Transport crew", "value": ticket["crew"] or "—"},
                {"key": "insurance", "label": "Insurance", "value": ticket["insurance"]},
                {"key": "how", "label": "On arrival",
                 "value": "Show this ticket. The receiving team scans the QR code to open the full record."},
                {"key": "expires", "label": "Expires", "value": ticket["expires"], "dateStyle": "PKDateStyleMedium", "timeStyle": "PKDateStyleShort"},
            ],
        },
    }


def _cert(data: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(data) if data.lstrip().startswith(b"-----BEGIN") else x509.load_der_x509_certificate(data)


def build_pkpass(ticket: dict, link: str) -> bytes:
    """pass.json + icons, a SHA-1 manifest, and a detached PKCS#7 signature by the Pass Type ID certificate + Apple WWDR."""
    files = {"pass.json": json.dumps(pass_json(ticket, link), ensure_ascii=False).encode(), **ICONS}
    manifest = json.dumps({name: hashlib.sha1(data).hexdigest() for name, data in files.items()}).encode()
    password = os.getenv("APPLE_PASS_P12_PASSWORD", "")
    key, cert, _ = pkcs12.load_key_and_certificates(Path(os.environ["APPLE_PASS_P12"]).read_bytes(), password.encode() if password else None)
    signature = (pkcs7.PKCS7SignatureBuilder().set_data(manifest).add_signer(cert, key, hashes.SHA256())
                 .add_certificate(_cert(Path(os.environ["APPLE_WWDR_CERT"]).read_bytes()))
                 .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in {**files, "manifest.json": manifest, "signature": signature}.items():
            z.writestr(name, data)
    return out.getvalue()


@app.get("/tickets/{tid}.pkpass")
def ticket_pkpass(tid: str):
    t = _live_ticket(tid)
    if not wallet_ready():
        raise HTTPException(404, "Apple Wallet signing is not configured (APPLE_PASS_TYPE_ID, APPLE_TEAM_ID, APPLE_PASS_P12, APPLE_WWDR_CERT)")
    return Response(build_pkpass(t["ticket"], t["link"]), media_type="application/vnd.apple.pkpass",
                    headers={"Content-Disposition": f'attachment; filename="uzima-{t["ticket"]["code"]}.pkpass"'})


@app.get("/tickets/{tid}", response_class=HTMLResponse)
def ticket_page(tid: str):
    t = _live_ticket(tid)
    k = t["ticket"]
    local = lambda iso: datetime.fromisoformat(iso).astimezone(TZ)
    eta, expires = local(k["eta"]), local(k["expires"])
    qr = segno.make_qr(t["link"], error="m").svg_inline(scale=1, omitsize=True, border=2, dark="#0A0B0D", light="#FFFFFF")
    wallet = (f'<a class="btn" href="{html.escape(k["wallet_url"])}">Add to Apple Wallet</a>' if k["wallet_url"] and wallet_ready()
              else "")   # Wallet is off unless the APPLE_* certificate is set; the web ticket is the ticket
    e = lambda v: html.escape(str(v if v is not None else "—"))
    return TICKET_HTML.substitute(
        code=e(k["code"]), from_city=e(k["from"]["city"].split(",")[0]), from_name=e(k["from"]["name"]),
        to_city=e(k["to"]["city"].split(",")[0]), to_name=e(k["to"]["name"]),
        patient=e(k["patient"]), condition=e(k["condition"]),
        transport=e(f"{k['mode'].capitalize()} · {k['travel_min']} min"),
        eta=e(eta.strftime("%-I:%M %p %Z")), ready=e(f"{k['ready_in_min']} min" if k["ready_in_min"] is not None else None),
        insurance=e(k["insurance"]), allergies=e(k["allergies"]), crew=e(k["crew"]), qr=qr, wallet=wallet, expires=e(expires.strftime("%b %-d, %-I:%M %p %Z")))


@app.post("/manifests/{twin_id}")
def manifest(twin_id: str, req: ManifestRequest):
    t = _store.get(twin_id)
    if not t or t["exp"] < datetime.now(timezone.utc).timestamp() or t["tries_left"] <= 0:
        raise HTTPException(404)
    if t["passcode"] is not None and req.passcode != t["passcode"]:
        t["tries_left"] -= 1
        return JSONResponse({"remainingAttempts": t["tries_left"]}, status_code=401)
    return {"files": [{"contentType": FHIR_JSON, "embedded": t["jwe"]}]}


@app.get("/view", response_class=HTMLResponse)
def view():
    """Built-in SMART Health Links viewer; the link rides in the URL fragment, so the key never reaches this server."""
    return VIEWER_HTML


@app.get("/health")
def health():
    return {"ok": True, "insurance": "stedi" if config.has_stedi() else "offline-mock", "twins": len(_store)}
