"""Simulated hospital responder for A2..An: weighted random, realistic reasons (FR-8)."""
import random

DECLINE_REASONS = {
    "cardiac_icu": ["no cardiac ICU bed", "cath lab team in a case", "on diversion", "no staffed bed"],
    "stroke_thrombectomy": ["no neuro ICU bed", "thrombectomy team in a case", "on diversion", "no staffed bed"],
    "trauma_adult": ["trauma bays full", "no surgeon available", "on diversion", "no staffed bed"],
    "trauma_burn": ["burn ICU full", "no burn surgeon tonight", "on diversion"],
    "childbirth": ["labor and delivery full", "no NICU bed", "no obstetrician available", "on diversion"],
    "trauma_pediatric": ["PICU full", "no pediatric surgeon available", "on diversion"],
}


def respond(specialty: str, is_large_center: bool, rng: random.Random | None = None) -> dict:
    """~12% no answer, ~8% 'call back in 5', otherwise yes at 45% (large) / 30% (small)."""
    r = rng or random
    x = r.random()
    if x < 0.12:
        return {"status": "no_answer"}
    if x < 0.20:
        return {"status": "callback_requested", "callback_in_min": 5}
    if r.random() < (0.45 if is_large_center else 0.30):
        return {"status": "available", "ready_in_min": r.choice(range(5, 35, 5))}
    return {"status": "declined", "decline_reason": r.choice(DECLINE_REASONS[specialty])}
