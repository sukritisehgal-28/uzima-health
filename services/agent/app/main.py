"""Sandbox entrypoint: one container = one hospital call, configured only by AGENT_HEADER and TRANSFER_ID."""
import asyncio
import json
import os

from services.agent.app.runner import run_agent
from services.shared.schemas import AgentHeader


def main() -> None:
    header = AgentHeader(**json.loads(os.environ["AGENT_HEADER"]))
    asyncio.run(run_agent(header, os.environ["TRANSFER_ID"]))


if __name__ == "__main__":
    main()
