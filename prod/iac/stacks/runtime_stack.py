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
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct  # noqa: F401 (re-exported for typing)

# Build context is the agent code directory (one level above prod/).
# The Dockerfile and entrypoint live next to the code they package; see
# prod/docker/agent/README.md for rationale.
AGENT_CODE_DIR = Path(__file__).resolve().parents[3] / "market-intelligence-agent"
AGENT_DOCKERFILE = "Dockerfile.agentcore"


class MiaRuntimeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        workspace_bucket: s3.IBucket,
        data_bucket: s3.IBucket,
        secrets: dict[str, sm.ISecret],
        gateway: agentcore.IGateway,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- AgentCore Memory ----------------------------------------------
        # AgentCore Memory name pattern: ^[a-zA-Z][a-zA-Z0-9_]{0,47}$
        # (no hyphens), so underscores instead of hyphens here.
        self.memory = agentcore.Memory(
            self, "MiaMemory",
            memory_name=f"{project}_memory_{env_name}",
            description=f"{project} {env_name} session memory",
            expiration_duration=Duration.days(30),
        )

        # --- Agent container image ----------------------------------------
        # AgentRuntimeArtifact.from_asset builds the Docker image, pushes
        # to a CDK-managed ECR repo, and wires permissions on bind().
        artifact = agentcore.AgentRuntimeArtifact.from_asset(
            directory=str(AGENT_CODE_DIR),
            file=AGENT_DOCKERFILE,
            platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=[
                ".venv/**", "data/**", "tests/**", "docs/**",
                "**/__pycache__/**", "**/*.pyc",
                ".pytest_cache/**", ".mypy_cache/**",
                "*.md", ".env*",
            ],
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
        # Memory r/w — `AgentCoreMemorySaver` needs CreateEvent (write a
        # checkpoint), ListEvents (load checkpoint history), and
        # RetrieveMemories (long-term retrieval, also used by store).
        # Scoped to the specific memory ARN by the construct.
        self.memory.grant_read(role)
        self.memory.grant(
            role,
            "bedrock-agentcore:CreateEvent",
            "bedrock-agentcore:ListEvents",
            "bedrock-agentcore:RetrieveMemories",
        )
        # Cognito user pool client — needed to read the client secret at
        # boot so the agent can mint OAuth tokens for the Gateway. The
        # specific user pool ARN is hardcoded here for the demo; lift to a
        # proper construct lookup if the gateway stack is rebuilt.
        role.add_to_policy(iam.PolicyStatement(
            actions=["cognito-idp:DescribeUserPoolClient"],
            resources=[f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/*"],
        ))

        # --- AgentCore Runtime --------------------------------------------
        self.runtime = agentcore.Runtime(
            self, "MiaRuntime",
            # AgentCore Runtime name pattern is the same as Memory (no hyphens).
            runtime_name=f"{project}_runtime_{env_name}",
            agent_runtime_artifact=artifact,
            execution_role=role,
            description=f"{project} {env_name} agent runtime",
            # tracing_enabled requires the account-level X-Ray trace segment
            # destination to be CloudWatch Logs (UpdateTraceSegmentDestination)
            # AND a CW Logs resource policy granting xray.amazonaws.com
            # PutLogEvents on aws/spans. Re-enable once those are configured.
            tracing_enabled=False,
            environment_variables={
                # Backend switches set in app/ during Phase 6a:
                # Durable checkpoint store via AgentCoreMemorySaver — required
                # for HITL approve/reject to work across container instances
                # (the AgentCore Runtime Playground generates a new
                # runtimeSessionId per click; in-memory state cannot survive).
                # Flip back to "memory" for a quick rollback without code changes.
                "CHECKPOINTER_BACKEND": "agentcore",
                "MCP_TRANSPORT": "gateway",
                "WORKSPACE_BACKEND": "s3",
                # Runtime-resolved values:
                "AGENTCORE_GATEWAY_URL": gateway.gateway_url or "",
                "WORKSPACE_S3_BUCKET": workspace_bucket.bucket_name,
                "MIA_MEMORY_ID": self.memory.memory_id,
                # Cognito client-credentials flow against the gateway's
                # default Cognito authorizer. IDs hardcoded for the demo
                # gateway; replace with construct outputs if rebuilt.
                "MIA_COGNITO_USER_POOL_ID": "us-east-1_KxtN9pzgf",
                "MIA_COGNITO_CLIENT_ID": "7m0gjbpfa66dh85qv3f6c9dfvt",
                "MIA_COGNITO_TOKEN_URL":
                    "https://miagatewaydemo-miagateway-d51291ee.auth.us-east-1.amazoncognito.com/oauth2/token",
                "MIA_COGNITO_SCOPES":
                    "miagatewaydemo-MiaGateway-D51291EE/read miagatewaydemo-MiaGateway-D51291EE/write",
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
