# `prod/docker/agent/` — placeholder

The agent Dockerfile and AgentCore entrypoint live next to the code they
build, not in this directory:

- **Dockerfile:** [`market-intelligence-agent/Dockerfile.agentcore`](../../../market-intelligence-agent/Dockerfile.agentcore)
- **Entrypoint:** [`market-intelligence-agent/entrypoint.py`](../../../market-intelligence-agent/entrypoint.py)

This keeps the Docker build context (`market-intelligence-agent/`)
identical to the directory the code already lives in — no cross-tree
COPY tricks, no oversized build contexts, no surprises.

The CDK `MiaRuntimeStack` references both via `DockerImageAsset(directory=market-intelligence-agent, file="Dockerfile.agentcore")`.
