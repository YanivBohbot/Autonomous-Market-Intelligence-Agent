"""CDK app entrypoint for the Market Intelligence Agent (MIA) deployment.

See prod/SPEC.md §8 for the stack list and dependency graph.
"""

import os

import aws_cdk as cdk

from stacks.identity_stack import MiaIdentityStack
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

identity = MiaIdentityStack(
    app, f"{PROJECT}-identity-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME, env=env,
)

storage = MiaStorageStack(
    app, f"{PROJECT}-storage-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME,
    kms_key=identity.kms_key,
    env=env,
)
storage.add_dependency(identity)

secrets = MiaSecretsStack(
    app, f"{PROJECT}-secrets-{ENV_NAME}",
    project=PROJECT, env_name=ENV_NAME, env=env,
)

for k, v in common_tags.items():
    cdk.Tags.of(app).add(k, v)

app.synth()
