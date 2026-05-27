"""CDK app entrypoint for the Market Intelligence Agent (MIA) deployment.

See prod/SPEC.md §8 for the stack list and dependency graph.
"""

import os

import aws_cdk as cdk

from stacks.browser_stack import MiaBrowserStack
from stacks.gateway_stack import MiaGatewayStack
from stacks.mcp_lambdas_stack import MiaMcpLambdasStack
from stacks.observability_stack import MiaObservabilityStack
from stacks.runtime_stack import MiaRuntimeStack
from stacks.secrets_stack import MiaSecretsStack
from stacks.storage_stack import MiaStorageStack

PROJECT = "mia"
ENV_NAME = os.environ.get("MIA_ENV", "demo")

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

common_tags = {
    "Project": PROJECT,
    "Env": ENV_NAME,
    "ManagedBy": "cdk",
}

app = cdk.App()

storage = MiaStorageStack(
    app, f"{PROJECT}-storage-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME, env=env,
)

secrets = MiaSecretsStack(
    app, f"{PROJECT}-secrets-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME, env=env,
)

browser = MiaBrowserStack(
    app, f"{PROJECT}-browser-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME, env=env,
)

mcp_lambdas = MiaMcpLambdasStack(
    app, f"{PROJECT}-mcp-lambdas-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME,
    workspace_bucket=storage.workspace_bucket,
    data_bucket=storage.data_bucket,
    env=env,
)
mcp_lambdas.add_dependency(storage)

gateway = MiaGatewayStack(
    app, f"{PROJECT}-gateway-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME,
    yfinance_fn=mcp_lambdas.yfinance_fn,
    filesystem_fn=mcp_lambdas.filesystem_fn,
    sqlite_crm_fn=mcp_lambdas.sqlite_crm_fn,
    env=env,
)
gateway.add_dependency(mcp_lambdas)

runtime = MiaRuntimeStack(
    app, f"{PROJECT}-runtime-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME,
    workspace_bucket=storage.workspace_bucket,
    data_bucket=storage.data_bucket,
    secrets=secrets.secrets,
    gateway=gateway.gateway,
    env=env,
)
runtime.add_dependency(secrets)
runtime.add_dependency(gateway)

observability = MiaObservabilityStack(
    app, f"{PROJECT}-observability-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME,
    alert_email=os.environ.get("MIA_ALERT_EMAIL") or None,
    env=env,
)

for k, v in common_tags.items():
    cdk.Tags.of(app).add(k, v)

app.synth()
