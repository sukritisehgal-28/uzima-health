import asyncio
import base64
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
from cryptography.x509.oid import NameOID

from services.handoff.app.main import FHIR_JSON, MAX_WRONG_PASSCODES, VIEWER, _store, app, decrypt_shl, ips_bundle, make_shl, with_demo_details
from services.shared.schemas import AgentResult, Case, InsuranceCheck, Specialty, Status, TransportEstimate, TwinRequest


def _req() -> TwinRequest:
    case = Case(age=62, sex="Male", specialty=Specialty.cardiac_icu, condition="STEMI", onset_or_last_known_well="2026-09-26T14:05:00-05:00",
                key_scores={"HEART": 7}, imaging_or_ecg="ST elevation V1-V4", blood_thinners="apixaban")
    t = TransportEstimate(est_ground_min=42, est_air_min=45, recommended_mode="ground", tier="within_target")
    calls = [AgentResult(agent_id="A1", hospital_id="delta_health", hospital="Delta Health", lat=0, lng=0, status=Status.available,
                         ready_in_min=10, transport=t, treatment_start_min=52)]
    return TwinRequest(case=case, accepted_hospital_id="delta_health", accepting_physician="Dr. A", transport=t, calls=calls)


def _twin(passcode: str = "123456") -> tuple[str, str]:
    r = _req()
    ins = InsuranceCheck(payer="mock", member_id_masked="***1", active=True, checked_at=datetime.now(timezone.utc))
    return make_shl(ips_bundle(r.case, r.accepted_hospital_id, r.accepting_physician, r.transport, r.calls, ins), passcode)


def test_ips_bundle_as_smart_health_link_roundtrip():
    twin_id, link = _twin()
    assert VIEWER.endswith("/view") and link.startswith(VIEWER + "#shlink:/")   # opens in the built-in viewer by default
    payload = json.loads(base64.urlsafe_b64decode(link.split("#shlink:/")[1] + "=="))
    assert payload["flag"] == "P" and len(twin_id) >= 43
    out = decrypt_shl(_store[twin_id]["jwe"], payload["key"])
    assert [s["title"] for s in out["entry"][0]["resource"]["section"]] == [
        "Medication Summary", "Allergies and Intolerances", "Problem List", "Vital Signs", "Results", "Treatment Given", "Plan of Care", "Transfer"]
    assert "Coverage" in {e["resource"]["resourceType"] for e in out["entry"]}


def _call(method: str, path: str, **kw) -> httpx.Response:
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://h") as h:
            return await h.request(method, path, **kw)
    return asyncio.run(go())


def test_manifest_limits_wrong_passcodes_per_spec():
    twin_id, _ = _twin("123456")
    r = _call("POST", f"/manifests/{twin_id}", json={"recipient": "x", "passcode": "000000"})
    assert r.status_code == 401 and r.json() == {"remainingAttempts": MAX_WRONG_PASSCODES - 1}
    ok = _call("POST", f"/manifests/{twin_id}", json={"recipient": "x", "passcode": "123456"})
    assert ok.status_code == 200 and ok.json()["files"][0]["contentType"] == FHIR_JSON
    for _ in range(MAX_WRONG_PASSCODES - 1):
        _call("POST", f"/manifests/{twin_id}", json={"recipient": "x", "passcode": "000000"})
    assert _call("POST", f"/manifests/{twin_id}", json={"recipient": "x", "passcode": "123456"}).status_code == 404   # locked for good


def test_viewer_page_and_cors_for_other_viewers():
    page = _call("GET", "/view")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "shlink:/" in page.text and "crypto.subtle" in page.text
    pre = _call("OPTIONS", "/manifests/x", headers={"Origin": "https://viewer.example.org", "Access-Control-Request-Method": "POST",
                                             "Access-Control-Request-Headers": "content-type"})
    assert pre.headers.get("access-control-allow-origin") in ("*", "https://viewer.example.org")


def test_ticket_is_created_with_the_record_and_opens_without_a_passcode():
    r = _call("POST", "/twins", json=_req().model_dump(mode="json")).json()
    k = r["ticket"]
    assert k["to"] == {"name": "Delta Health System-The Medical Center", "short": "Delta Health", "city": "Greenville, MS"}
    assert k["from"]["city"] == "Indianola, MS" and k["mode"] == "ground" and k["travel_min"] == 42 and k["ready_in_min"] == 10
    assert k["code"].startswith("UZ-") and k["wallet_url"] is None            # no Apple certificate configured here
    assert k["allergies"] == "No known drug allergies" and k["crew"].startswith("Advanced life support")
    page = _call("GET", f"/tickets/{k['id']}")
    assert page.status_code == 200 and "Greenville" in page.text and k["code"] in page.text and "<svg" in page.text
    assert "No known drug allergies" in page.text and "paramedic" in page.text
    assert "passcode" not in r and "passcode" not in page.text.lower()
    assert _call("GET", f"/tickets/{k['id']}.pkpass").status_code == 404
    assert _call("GET", "/tickets/not-a-ticket").status_code == 404


def _self_signed(cn: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    return key, cert


def test_wallet_pass_is_hashed_and_signed(tmp_path, monkeypatch):
    key, cert = _self_signed("Pass Type ID: pass.test.uzima")
    _, wwdr = _self_signed("Test WWDR")
    (tmp_path / "pass.p12").write_bytes(pkcs12.serialize_key_and_certificates(b"pass", key, cert, None, serialization.BestAvailableEncryption(b"pw")))
    (tmp_path / "wwdr.pem").write_bytes(wwdr.public_bytes(serialization.Encoding.PEM))
    for k, v in {"APPLE_PASS_TYPE_ID": "pass.test.uzima", "APPLE_TEAM_ID": "TEAM123456", "APPLE_PASS_P12": str(tmp_path / "pass.p12"),
                 "APPLE_PASS_P12_PASSWORD": "pw", "APPLE_WWDR_CERT": str(tmp_path / "wwdr.pem")}.items():
        monkeypatch.setenv(k, v)
    r = _call("POST", "/twins", json=_req().model_dump(mode="json")).json()
    k = r["ticket"]
    assert k["wallet_url"].endswith(f"/tickets/{k['id']}.pkpass")
    res = _call("GET", f"/tickets/{k['id']}.pkpass")
    assert res.status_code == 200 and res.headers["content-type"] == "application/vnd.apple.pkpass"
    z = zipfile.ZipFile(io.BytesIO(res.content))
    assert {"pass.json", "manifest.json", "signature", "icon.png", "icon@2x.png"} <= set(z.namelist())
    manifest = json.loads(z.read("manifest.json"))
    assert set(manifest) == set(z.namelist()) - {"manifest.json", "signature"}
    assert all(hashlib.sha1(z.read(n)).hexdigest() == h for n, h in manifest.items())
    p = json.loads(z.read("pass.json"))
    assert p["barcodes"][0]["message"] == r["shlink"] and p["boardingPass"]["primaryFields"][1]["value"] == "Greenville"
    assert p["passTypeIdentifier"] == "pass.test.uzima" and "passcode" not in json.dumps(p).lower()
    signers = {c.subject.rfc4514_string() for c in pkcs7.load_der_pkcs7_certificates(z.read("signature"))}
    assert signers == {"CN=Pass Type ID: pass.test.uzima", "CN=Test WWDR"}


def test_demo_details_fill_gaps_but_never_override_the_clinician():
    case, filled = with_demo_details(_req().case)
    assert case.imaging_or_ecg == "ST elevation V1-V4" and case.key_scores == {"HEART": 7}     # the clinician's own values stay
    assert case.vitals and case.vitals_at and case.labs and case.treatment_given and case.allergies and case.certification and case.consent
    assert "vitals" in filled and "imaging_or_ecg" not in filled and "key_scores" not in filled


def test_record_carries_emtala_transfer_content():
    r = _call("POST", "/twins", json=_req().model_dump(mode="json")).json()
    payload = json.loads(base64.urlsafe_b64decode(r["shlink"].split("#shlink:/")[1] + "=="))
    assert "flag" not in payload                                                   # no passcode on our links
    m = _call("POST", payload["url"].split("8004", 1)[-1], json={"recipient": "x"}).json()
    bundle = decrypt_shl(m["files"][0]["embedded"], payload["key"])
    kinds = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert {"AllergyIntolerance", "DiagnosticReport", "Coverage"} <= set(kinds)
    vitals = [e["resource"] for e in bundle["entry"] if e["resource"].get("category", [{}])[0].get("text") == "vital-signs"]
    assert vitals and all(v.get("effectiveDateTime") for v in vitals)
    sections = {s["title"]: s for s in bundle["entry"][0]["resource"]["section"]}
    transfer = json.loads(sections["Transfer"]["text"]["div"].split(">", 1)[1].rsplit("</div>", 1)[0])
    assert transfer["certification"]["summary"] and transfer["consent"] and transfer["treatment_given"] and transfer["crew"]
    assert "vitals" in transfer["demo_details"]                                   # labeled as fictional demo data
