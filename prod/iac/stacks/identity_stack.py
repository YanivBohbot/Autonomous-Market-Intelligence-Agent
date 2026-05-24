"""IdentityStack — KMS CMK `alias/mia` shared by S3 buckets and CloudWatch Logs.

Per prod/SPEC.md §4.7 finding F2: a customer-managed KMS key lets the baseline
SCP enforce non-KMS-deny uploads. The key is created here, exported by ARN, and
imported by downstream stacks (storage, observability).

IAM roles for Runtime / Gateway / Lambdas are defined in their respective
compute stacks — keeping each role next to the resource it serves keeps blast-
radius reasoning local and avoids a 'god identity stack' anti-pattern.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_kms as kms
from constructs import Construct


class MiaIdentityStack(Stack):
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

        self.kms_key = kms.Key(
            self, "MiaCmk",
            alias=f"alias/{project}",
            description=f"{project} ({env_name}) — encrypts S3 and CloudWatch Logs",
            enable_key_rotation=True,
            # Demo env: destroy with the stack. In a real prod env this would be
            # RETAIN to prevent accidental data lockout.
            removal_policy=RemovalPolicy.DESTROY if env_name == "demo" else RemovalPolicy.RETAIN,
        )

        CfnOutput(
            self, "KmsKeyArn",
            value=self.kms_key.key_arn,
            export_name=f"{project}-{env_name}-kms-key-arn",
        )
