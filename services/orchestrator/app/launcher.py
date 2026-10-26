"""Launch one agent per hospital: in-process (default) or one Kubernetes Job per hospital (LAUNCH_MODE=k8s)."""
import asyncio
import json
import logging

from services.shared import config
from services.shared.schemas import AgentHeader

log = logging.getLogger("launcher")


class LocalLauncher:
    """Every agent as an asyncio task in this process: the no-Kubernetes fallback, and the default for dev."""

    async def launch(self, transfer_id: str, headers: list[AgentHeader]) -> None:
        from services.agent.app.runner import run_agent
        await asyncio.gather(*(run_agent(h, transfer_id) for h in headers), return_exceptions=True)


class K8sLauncher:
    """One Job per hospital from the same image; only AGENT_HEADER and TRANSFER_ID differ (infra/k8s/agent-job-template.yaml)."""

    async def launch(self, transfer_id: str, headers: list[AgentHeader]) -> None:
        from kubernetes import client as k8s, config as kcfg  # lazy
        kcfg.load_incluster_config() if config.env("KUBERNETES_SERVICE_HOST") else kcfg.load_kube_config()
        api, ns = k8s.BatchV1Api(), config.env("K8S_NAMESPACE", "project-uzima")
        for h in headers:
            env = [k8s.V1EnvVar(name="AGENT_HEADER", value=json.dumps(h.model_dump(mode="json"))),
                   k8s.V1EnvVar(name="TRANSFER_ID", value=transfer_id)]
            container = k8s.V1Container(name="agent", image=config.env("AGENT_IMAGE", "project-uzima/agent:latest"), env=env,
                                        env_from=[k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="project-uzima-secrets"))])
            job = k8s.V1Job(metadata=k8s.V1ObjectMeta(generate_name=f"agent-{h.agent_id.lower()}-"),
                            spec=k8s.V1JobSpec(backoff_limit=0, ttl_seconds_after_finished=300, template=k8s.V1PodTemplateSpec(
                                spec=k8s.V1PodSpec(restart_policy="Never", containers=[container]))))
            await asyncio.to_thread(api.create_namespaced_job, ns, job)
        log.info("launched %d jobs for %s", len(headers), transfer_id)


def get_launcher():
    return K8sLauncher() if config.launch_mode() == "k8s" else LocalLauncher()
