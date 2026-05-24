"""RuntimeStack — AgentCore Runtime + AgentCore Memory.

Builds the agent Docker image from prod/docker/agent/, pushes to a CDK-
managed ECR repo, and provisions an AgentCore Runtime that hosts it.
Wires Secrets Manager + Gateway URL into the container environment.

Per prod/SPEC.md §3.1 + §4.1: Runtime execution role limited to the four
secret ARNs, the Gateway invoke action, the Memory create/retrieve actions,
S3 read on mia-data + read/write on mia-workspace. No wildcards.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct

DOCKER_DIR = Path(__file__).resolve().parents[2] / "docker" / "agent"


class MiaRuntimeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        kms_key: kms.IKey,
        workspace_bucket: s3.IBucket,
        data_bucket: s3.IBucket,
        secrets: dict[str, sm.ISecret],
        gateway: agentcore.IGateway,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- AgentCore Memory ----------------------------------------------
        self.memory = agentcore.Memory(
            self, "MiaMemory",
            memory_name=f"{project}-memory-{env_name}",
            description=f"{project} {env_name} session memory",
            expiration_duration=Duration.days(30),
            kms_key=kms_key,
        )

        # --- Agent container image ----------------------------------------
        self.image = ecr_assets.DockerImageAsset(
            self, "AgentImage",
            directory=str(DOCKER_DIR),
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        # --- Runtime execution role ---------------------------------------
        role = iam.Role(
            self, "RuntimeRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description=f"{project}-{env_name} AgentCore Runtime execution role",
        )
        # Logs
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )
        # Secrets — restricted to the four exact ARNs.
        for secret in secrets.values():
            secret.grant_read(role)
        # S3
        workspace_bucket.grant_read_write(role)
        data_bucket.grant_read(role)
        # Gateway invoke
        gateway.grant_invoke(role)
        # Memory r/w
        self.memory.grant_read(role)
        self.memory.grant(role, "bedrock-agentcore:CreateEvent")
        # KMS — encrypt/decrypt for SSE-KMS objects.
        kms_key.grant_encrypt_decrypt(role)

        # --- AgentCore Runtime --------------------------------------------
        artifact = agentcore.AgentRuntimeArtifact.from_container_image(self.image)

        self.runtime = agentcore.Runtime(
            self, "MiaRuntime",
            runtime_name=f"{project}-runtime-{env_name}",
            agent_runtime_artifact=artifact,
            execution_role=role,
            description=f"{project} {env_name} agent runtime",
            tracing_enabled=True,
            environment_variables={
                # Backend switches set in app/ during Phase 6a:
                "CHECKPOINTER_BACKEND": "memory",
                "MCP_TRANSPORT": "gateway",
                "WORKSPACE_BACKEND": "s3",
                # Runtime-resolved values:
                "AGENTCORE_GATEWAY_URL": gateway.gateway_url or "",
                "WORKSPACE_S3_BUCKET": workspace_bucket.bucket_name,
                "MIA_MEMORY_ID": self.memory.memory_id,
                # Secret ARNs — container reads values via boto3 at startup.
                "OPENAI_API_KEY_ARN": secrets["openai-api-key"].secret_arn,
                "PINECONE_API_KEY_ARN": secrets["pinecone-api-key"].secret_arn,
                "TAVILY_API_KEY_ARN": secrets["tavily-api-key"].secret_arn,
                "EMAIL_PASSWORD_ARN": secrets["email-password"].secret_arn,
                # Static config the entrypoint passes through:
                "OPENAI_MODEL": "gpt-4o-mini",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
                "PINECONE_INDEX_NAME": f"{project}-rag",
                "EMAIL_SENDER": "mia-agent@example.com",
                "EMAIL_SMTP_SERVER": "smtp.gmail.com",
                "EMAIL_SMTP_PORT": "587",
                "LOG_LEVEL": "INFO",
            },
        )

        CfnOutput(self, "RuntimeArn",
                  value=self.runtime.agent_runtime_arn,
                  export_name=f"{project}-{env_name}-runtime-arn")
        CfnOutput(self, "MemoryId",
                  value=self.memory.memory_id,
                  export_name=f"{project}-{env_name}-memory-id")
        CfnOutput(self, "ImageUri",
                  value=self.image.image_uri,
                  export_name=f"{project}-{env_name}-agent-image-uri")
