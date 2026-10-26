"""Environment-driven settings. Every integration has a mock fallback, so the skeleton runs with no keys.

Add a key to .env and the real integration switches on; remove it and the mock takes over again.
"""
import os

DEFAULT_URLS = {
    "orchestrator": "http://localhost:8000",
    "sync_openai": "http://localhost:8001",
    "sync_twilio": "http://localhost:8002",
    "collector": "http://localhost:8003",
    "handoff": "http://localhost:8004",
}
URL_ENV = {"orchestrator": "ORCHESTRATOR_URL", "sync_openai": "OPENAI_SYNC_URL", "sync_twilio": "TWILIO_SYNC_URL",
           "collector": "COLLECTOR_URL", "handoff": "HANDOFF_URL"}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def url(service: str) -> str:
    return env(URL_ENV[service], DEFAULT_URLS[service])


def has_openai() -> bool:
    """Legacy direct Realtime voice only; text generation uses has_bedrock()."""
    return bool(env("OPENAI_API_KEY"))


def has_bedrock() -> bool:
    return env("USE_BEDROCK", "0") == "1"


def has_twilio() -> bool:
    return env("TWILIO_ENABLED", "1") == "1" and all(env(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))


def has_stedi() -> bool:
    return bool(env("STEDI_TEST_API_KEY"))


def use_aws() -> bool:
    return env("USE_AWS", "0") == "1"


def has_dynamo() -> bool:
    return use_aws() and bool(env("DYNAMODB_TABLE"))


def has_location() -> bool:
    return use_aws() and bool(env("AWS_LOCATION_ROUTE_CALCULATOR"))


def launch_mode() -> str:
    return env("LAUNCH_MODE", "local")          # "local" (in-process swarm) or "k8s" (one Job per hospital)


def sim_time_scale() -> float:
    return float(env("SIM_TIME_SCALE", "1"))   # 0 in tests; 1 on stage (answers land over 5-45 s)


def sim_a1_answer() -> str:
    return env("SIM_A1_ANSWER", "random")      # "available" makes A1 say yes when there is no live call


def integrations() -> dict:
    return {"openai": "live" if has_bedrock() else "mock", "twilio": "live" if has_twilio() else "mock",
            "stedi": "live" if has_stedi() else "mock", "dynamodb": "live" if has_dynamo() else "memory",
            "aws_location": "live" if has_location() else "estimates", "launcher": launch_mode()}
