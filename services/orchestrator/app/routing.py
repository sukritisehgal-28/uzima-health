"""Transport estimates: the verified estimate model in data/hospitals.json by default; AWS Location road routing
when USE_AWS=1 and AWS_LOCATION_ROUTE_CALCULATOR are set (ground time only; air stays estimated)."""
import logging
from functools import lru_cache

from services.shared import config
from services.shared.schemas import TransportEstimate

log = logging.getLogger("routing")


@lru_cache(maxsize=256)
def _road_minutes(src: tuple, dst: tuple) -> float | None:
    try:
        import boto3  # lazy
        r = boto3.client("location", region_name=config.env("AWS_REGION")).calculate_route(
            CalculatorName=config.env("AWS_LOCATION_ROUTE_CALCULATOR"),
            DeparturePosition=[src[1], src[0]], DestinationPosition=[dst[1], dst[0]])
        return r["Summary"]["DurationSeconds"] / 60
    except Exception as e:
        log.warning("AWS Location failed, using estimate: %s", e)
        return None


def transport(sending: dict, center: dict, window: dict, loading_min: int = 10) -> TransportEstimate:
    ground, air = center["est_ground_min"], center["est_air_min"]
    if config.has_location():
        road = _road_minutes((sending["lat"], sending["lng"]), (center["lat"], center["lng"]))
        if road is not None:
            ground = round(road) + loading_min
    budget, hard = window["transport_budget_min"], window["hard_max_min"]
    if ground <= budget:
        tier, mode = "within_target", "ground"
    elif air <= budget:
        tier, mode = "within_target", "air"
    elif min(ground, air) <= hard:
        tier, mode = "within_hard_max", "ground" if ground <= air else "air"
    else:
        tier, mode = "outside", "air"
    return TransportEstimate(est_ground_min=ground, est_air_min=air, recommended_mode=mode, tier=tier)
