"""BrowserStack — Amazon Bedrock AgentCore Custom Browser + recording bucket.

The system ARN ``aws.browser.v1`` does not support session recording, so we
provision a Custom Browser with recording=ON pointed at a dedicated S3
bucket (KMS-encrypted, 30-day lifecycle).

The browser uses PUBLIC network mode (matches today's free-public-egress
demo workload). Move to VPC mode when private resources are needed.
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct


class MiaBrowserStack(Stack):
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

        # --- KMS key for recording bucket ---
        key = kms.Key(
            self, "BrowserKey",
            description=f"{project}-{env_name} browser recordings",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Recording bucket ---
        bucket = s3.Bucket(
            self, "BrowserRecordings",
            bucket_name=f"{project}-browser-recordings-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=key,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-30d",
                    expiration=Duration.days(30),
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                )
            ],
        )
        self.recording_bucket = bucket

        # --- Browser execution role ---
        # Trust policy with confused-deputy guards (SourceAccount + SourceArn).
        exec_role = iam.Role(
            self, "BrowserExecRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"
                    },
                },
            ),
            description=f"{project}-{env_name} AgentCore Browser execution role",
        )
        bucket.grant_write(exec_role)
        key.grant_encrypt(exec_role)
        self.exec_role = exec_role

        # --- Custom Browser ---
        # AgentCore name pattern: [a-zA-Z][a-zA-Z0-9_]{0,47} (no hyphens).
        browser = agentcore.BrowserCustom(
            self, "MiaBrowser",
            browser_custom_name=f"{project}_browser_{env_name}",
            description=f"{project} {env_name} browser with S3 recording",
            execution_role=exec_role,
            network_configuration=agentcore.BrowserNetworkConfiguration.using_public_network(),
            recording_config=agentcore.RecordingConfig(
                enabled=True,
                s3_location={"bucket_name": bucket.bucket_name, "object_key": "sessions/"},
            ),
        )
        # The L2 exposes the ARN as an attribute; check `dir(browser)` for the
        # exact property name (likely `browser_custom_arn`) and store it on self.
        # If the attribute does not exist, fall back to the `.node.default_child`
        # CfnBrowserCustom and use `.attr_browser_arn` (L1 escape hatch).
        if hasattr(browser, "browser_custom_arn"):
            self.browser_arn = browser.browser_custom_arn
        elif hasattr(browser, "browser_arn"):
            self.browser_arn = browser.browser_arn
        else:
            cfn = browser.node.default_child
            self.browser_arn = cfn.attr_browser_arn  # type: ignore[attr-defined]

        CfnOutput(
            self, "BrowserArn", value=self.browser_arn,
            export_name=f"{project}-{env_name}-browser-arn",
        )
        CfnOutput(
            self, "RecordingBucket", value=bucket.bucket_name,
            export_name=f"{project}-{env_name}-browser-bucket",
        )
