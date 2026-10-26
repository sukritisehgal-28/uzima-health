"""Collector storage: in memory by default; DynamoDB write-through when USE_AWS=1 and DYNAMODB_TABLE are set."""
import json
import logging
import os
import time
from collections import defaultdict

log = logging.getLogger("collector.storage")


class MemoryStore:
    mode = "memory"

    def __init__(self) -> None:
        self.events: dict[str, list] = defaultdict(list)             # transfer_id -> call events
        self.transfer_events: dict[str, list] = defaultdict(list)    # transfer_id -> transfer events
        self.results: dict[str, dict] = defaultdict(dict)            # transfer_id -> agent_id -> result
        self.memory: dict[str, dict] = {}                            # hospital_id -> last answer (bed memory)
        self.by_hospital: dict[str, list] = defaultdict(list)        # hospital_id -> events (EMTALA log)

    def add_event(self, ev: dict) -> None:
        self.events[ev["transfer_id"]].append(ev)
        self.by_hospital[ev["hospital_id"]].append(ev)

    def add_transfer_event(self, ev: dict) -> None:
        self.transfer_events[ev["transfer_id"]].append(ev)

    def add_result(self, r: dict) -> None:
        self.results[r["transfer_id"]][r["agent_id"]] = r
        self.memory[r["hospital_id"]] = {"status": r["status"], "ready_in_min": r.get("ready_in_min"),
                                         "reason": r.get("decline_reason"), "at": r.get("answered_at"), "ts": time.time()}


class DynamoStore(MemoryStore):
    """Writes every record to DynamoDB (pk/sk design in infra/aws/dynamodb-table.json); reads stay in memory for speed."""
    mode = "dynamodb"

    def __init__(self) -> None:
        super().__init__()
        import boto3  # lazy: only needed when AWS is on
        self.table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION")).Table(os.environ["DYNAMODB_TABLE"])

    def _put(self, item: dict) -> None:
        try:
            self.table.put_item(Item={k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in item.items()})
        except Exception as e:  # never break the demo on a storage error
            log.warning("dynamodb put failed: %s", e)

    def add_event(self, ev: dict) -> None:
        super().add_event(ev)
        self._put({"pk": f"TRANSFER#{ev['transfer_id']}", "sk": f"EVENT#{ev['at']}#{ev['agent_id']}", **ev})

    def add_transfer_event(self, ev: dict) -> None:
        super().add_transfer_event(ev)
        self._put({"pk": f"TRANSFER#{ev['transfer_id']}", "sk": f"TEVENT#{ev['at']}#{ev['type']}", **ev})

    def add_result(self, r: dict) -> None:
        super().add_result(r)
        self._put({"pk": f"TRANSFER#{r['transfer_id']}", "sk": f"RESULT#{r['agent_id']}", "data": r})
        self._put({"pk": "MEMORY", "sk": r["hospital_id"], "data": self.memory[r["hospital_id"]], "ttl": int(time.time()) + 1800})


def make_store() -> MemoryStore:
    from services.shared import config
    if config.has_dynamo():
        try:
            return DynamoStore()
        except Exception as e:
            log.warning("DynamoDB unavailable, using memory: %s", e)
    return MemoryStore()
