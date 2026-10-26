"""Schemas shared by every Project Uzima service."""
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Specialty(str, Enum):
    """Which capability the patient needs; keys match data/hospitals.json demo_cases."""
    cardiac_icu = "cardiac_icu"            # STEMI: cath lab + cardiac ICU
    stroke_thrombectomy = "stroke_thrombectomy"
    trauma_adult = "trauma_adult"          # Level I/II trauma center
    trauma_burn = "trauma_burn"            # verified burn center
    trauma_pediatric = "trauma_pediatric"  # pediatric trauma center
    childbirth = "childbirth"              # high-risk delivery: labor and delivery, emergency C-section, NICU


class Case(BaseModel):
    """What the sending doctor reports. Fictional data only in the demo."""
    age: int
    sex: str
    specialty: Specialty
    condition: str                      # "STEMI, anterior" / "LVO stroke, left MCA" / "MVC, head injury"
    onset_or_last_known_well: str       # ISO time; drives the remaining survival window
    key_scores: dict = Field(default_factory=dict)   # e.g. {"NIHSS": 18} or {"GCS": 9}
    imaging_or_ecg: Optional[str] = None
    blood_thinners: Optional[str] = None
    weight_kg: Optional[float] = None
    is_pediatric: bool = False
    sending_hospital_id: str = "south_sunflower"
    sending_physician: str = "[Dr. name]"
    callback_phone: str = "[demo phone]"
    window_min: Optional[int] = None    # clinician's "care within N minutes"; overrides the case's default transport budget
    # Handoff content (EMTALA 42 CFR 489.24(e)(2)(iii) records + clinical handoff). All optional; the handoff service
    # fills empty ones from data/demo_patients.json (fictional) so the demo record is complete.
    vitals: dict = Field(default_factory=dict)          # {"Heart rate": "102 /min", "Blood pressure": "118/76 mmHg", ...}
    vitals_at: Optional[str] = None                     # ISO time the vitals were taken
    labs: dict = Field(default_factory=dict)            # {"Troponin I": "2.8 ng/mL (high)"}
    treatment_given: list[str] = Field(default_factory=list)   # "Aspirin 324 mg chewed, 14:12"
    response_to_treatment: Optional[str] = None
    allergies: Optional[str] = None                     # "No known drug allergies" / "Penicillin (rash)"
    pending: list[str] = Field(default_factory=list)    # care still to be done
    certification: Optional[str] = None                 # physician's risks/benefits summary for the transfer
    consent: Optional[str] = None                       # patient consent or written request


class TransportEstimate(BaseModel):
    est_ground_min: int
    est_air_min: int
    recommended_mode: Literal["ground", "air"]
    tier: Literal["within_target", "within_hard_max", "outside"]


class AgentHeader(BaseModel):
    """The only thing that differs between sandbox clones."""
    agent_id: str
    hospital_id: str
    hospital: str
    phone: str                          # demo: a teammate's number, never the real hospital
    lat: float
    lng: float
    specialty: Specialty
    capability_question: str            # Q1 wording for this specialty
    transport: TransportEstimate
    live: bool = False                  # True only for A1


class Status(str, Enum):
    calling = "calling"
    available = "available"
    declined = "declined"
    no_answer = "no_answer"
    callback_requested = "callback_requested"
    held = "held"
    released = "released"
    accepted = "accepted"


class TranscriptLine(BaseModel):
    speaker: Literal["agent", "hospital"]
    text: str
    at: datetime


# The four events every call path emits, so the voice layer can be swapped
# without touching the dashboard. A full AgentResult follows call_ended.
class CallEvent(BaseModel):
    type: Literal["call_started", "call_answered", "answer_recorded", "call_ended"]
    transfer_id: str = ""
    agent_id: str
    hospital_id: str
    at: datetime
    data: dict = Field(default_factory=dict)   # answer_recorded: {bed: bool, ready_in_min, reason}


class AgentResult(BaseModel):
    transfer_id: str = ""
    agent_id: str
    hospital_id: str
    hospital: str
    lat: float
    lng: float
    status: Status
    ready_in_min: Optional[int] = None
    decline_reason: Optional[str] = None
    transport: TransportEstimate
    treatment_start_min: Optional[int] = None   # max(transport, ready_in) + handoff
    transcript: list[TranscriptLine] = Field(default_factory=list)
    answered_at: Optional[datetime] = None
    source: Literal["live", "simulated"] = "simulated"
    error: Optional[str] = None


class InsuranceCheck(BaseModel):
    payer: str
    member_id_masked: str
    active: Optional[bool] = None
    plan: Optional[str] = None
    checked_at: Optional[datetime] = None
    source: str = "stedi-mock"


class HandoffTwin(BaseModel):
    """Encrypted, structured record that travels with the patient after acceptance."""
    twin_id: str
    case: Case
    accepted_hospital_id: str
    accepting_physician: str
    transport: TransportEstimate
    calls: list[AgentResult]                 # every hospital asked, every answer
    insurance: Optional[InsuranceCheck] = None
    created_at: datetime
    emtala_log_ref: str
    shlink: Optional[str] = None            # SMART Health Link to the encrypted IPS bundle


class TransferEvent(BaseModel):
    """Transfer-level events for the dashboard (the four call events stay per agent)."""
    transfer_id: str
    type: Literal["search_started", "held", "released", "accepted", "twin_ready"]
    hospital_id: Optional[str] = None
    at: datetime
    data: dict = Field(default_factory=dict)


class AcceptRequest(BaseModel):
    hospital_id: Optional[str] = None           # default: the recommended center
    accepting_physician: str = "[accepting physician]"


class TwinRequest(BaseModel):
    case: Case
    accepted_hospital_id: str
    accepting_physician: str
    transport: TransportEstimate
    calls: list[AgentResult]
    insurance_test: Optional[dict] = None       # Stedi mock member only: {"payer_id","member_id","first","last","dob"}
