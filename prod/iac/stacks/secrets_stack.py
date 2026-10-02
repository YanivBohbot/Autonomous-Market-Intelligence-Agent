"""SecretsStack — Secrets Manager entries for external SaaS credentials.

Creates EMPTY secrets (no values) and exports their ARNs. Real values are
populated outside CDK via `aws secretsmanager put-secret-value` so secrets
never touch the repo or CloudFormation templates. See prod/iac/README.md.

Per prod/SPEC.md §4.3 — kept to the four v1 secrets. Voice/LiveKit secrets
(LIVEKIT_*, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY) are intentionally not
deployed in v1 — voice is out of scope and the redaction filter still
covers them in code.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct


class MiaSecretsStack(Stack):
    SECRET_KEYS = (
        "openai-api-key",
        "pinecone-api-key",
        "tavily-api-key",
        "email-password",
    )

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        removal = RemovalPolicy.DESTROY if env_name == "demo" else RemovalPolicy.RETAIN
        self.secrets: dict[str, sm.Secret] = {}

        for key in self.SECRET_KEYS:
            secret = sm.Secret(
                self, _to_pascal(key),
                # -v2: on 2026-10-02 the original `{project}/{key}` secrets
                # were found deleted directly in Secrets Manager outside CDK
                # (CloudFormation drift: DELETED, confirmed via
                # detect-stack-drift), while this stack's state still had
                # them as CREATE_COMPLETE with dead ARNs. `Name` is one of
                # the few AWS::SecretsManager::Secret properties that forces
                # a true CloudFormation replacement on update (confirmed via
                # a real ChangeSet: Replacement=True) -- the only way to get
                # fresh, working ARNs on `cdk deploy` without destroying this
                # stack, whose ARNs are cross-stack exports mia-runtime-demo
                # imports (a stack destroy fails outright while an export is
                # in use). Verified empirically that merely adding
                # GenerateSecretString (even with exclude_punctuation) does
                # NOT force replacement -- CDK already defaults it to {}, so
                # that alone is a no-op.
                secret_name=f"{project}/{key}-v2",
                description=f"{project} {env_name} — {key}; populate via put-secret-value",
                removal_policy=removal,
                # Unescaped punctuation in a generated value could break
                # downstream parsing once injected as a container env var.
                # Thrown away immediately -- put-secret-value overwrites it
                # with the real key right after deploy.
                generate_secret_string=sm.SecretStringGenerator(exclude_punctuation=True),
            )
            self.secrets[key] = secret
            CfnOutput(
                self, f"{_to_pascal(key)}Arn",
                value=secret.secret_arn,
                export_name=f"{project}-{env_name}-secret-{key}-arn",
            )


def _to_pascal(s: str) -> str:
    return "".join(p.capitalize() for p in s.split("-"))
