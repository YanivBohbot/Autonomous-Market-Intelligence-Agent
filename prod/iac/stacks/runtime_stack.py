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
        browser_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- AgentCore Memory ----------------------------------------------
        # AgentCore Memory name pattern: ^[a-zA-Z][a-zA-Z0-9_]{0,47}$
        # (no hyphens), so underscores instead of hyphens here.
        self.memory = agentcore.Memory(
            self,
            "MiaMemory",
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
                ".venv/**",
                "data/**",
                "tests/**",
                "docs/**",
                "**/__pycache__/**",
                "**/*.pyc",
                ".pytest_cache/**",
                ".mypy_cache/**",
                "*.md",
                ".env*",
            ],
        )

        # --- Runtime execution role ---------------------------------------
        role = iam.Role(
            self,
            "RuntimeRole",
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
        # AgentCore Browser data-plane: start/stop/get sessions plus the
        # ConnectBrowserAutomationStream WebSocket data-plane call. The arn
        # is the CustomBrowser ARN minted by MiaBrowserStack.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:StartBrowserSession",
                    "bedrock-agentcore:StopBrowserSession",
                    "bedrock-agentcore:GetBrowserSession",
                    "bedrock-agentcore:ConnectBrowserAutomationStream",
                ],
                resources=[browser_arn],
            )
        )
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
        # SES — agent's send_email tool sends via Amazon SES.
        # Scope to the verified sender identity ARN only.
        ses_sender = "yanivbohbot5@gmail.com"
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[
                    f"arn:aws:ses:{self.region}:{self.account}:identity/{ses_sender}"
                ],
            )
        )

        # Cognito user pool client — needed to read the client secret at
        # boot so the agent can mint OAuth tokens for the Gateway. The
        # specific user pool ARN is hardcoded here for the demo; lift to a
        # proper construct lookup if the gateway stack is rebuilt.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cognito-idp:DescribeUserPoolClient"],
                resources=[
                    f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/*"
                ],
            )
        )

        # --- AgentCore Runtime --------------------------------------------
        self.runtime = agentcore.Runtime(
            self,
            "MiaRuntime",
            # AgentCore Runtime name pattern is the same as Memory (no hyphens).
            runtime_name=f"{project}_runtime_{env_name}",
            agent_runtime_artifact=artifact,
            execution_role=role,
            description=f"{project} {env_name} agent runtime",
            tracing_enabled=False,
            environment_variables={
                "BROWSER_BACKEND": "agentcore",
                "BROWSER_TOOL_ID": browser_arn,
                "BROWSER_IDLE_TTL_S": "300",
                "CHECKPOINTER_BACKEND": "agentcore",
                "MCP_TRANSPORT": "gateway",
                "WORKSPACE_BACKEND": "s3",
                "AGENTCORE_GATEWAY_URL": gateway.gateway_url or "",
                "WORKSPACE_S3_BUCKET": workspace_bucket.bucket_name,
                "MIA_MEMORY_ID": self.memory.memory_id,
                "MIA_COGNITO_USER_POOL_ID": "us-east-1_KxtN9pzgf",
                "MIA_COGNITO_CLIENT_ID": "7m0gjbpfa66dh85qv3f6c9dfvt",
                "MIA_COGNITO_TOKEN_URL": "https://miagatewaydemo-miagateway-d51291ee.auth.us-east-1.amazoncognito.com/oauth2/token",
                "MIA_COGNITO_SCOPES": "miagatewaydemo-MiaGateway-D51291EE/read miagatewaydemo-MiaGateway-D51291EE/write",
                "OPENAI_API_KEY_ARN": secrets["openai-api-key"].secret_arn,
                "PINECONE_API_KEY_ARN": secrets["pinecone-api-key"].secret_arn,
                "TAVILY_API_KEY_ARN": secrets["tavily-api-key"].secret_arn,
                # EMAIL_PASSWORD_ARN dropped — send_email uses SES via boto3
                # (no SMTP login). The secret is kept in Secrets Manager for
                # rollback if we ever revert to smtplib.
                "OPENAI_MODEL": "gpt-4o-mini",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
                "PINECONE_INDEX_NAME": f"{project}-rag",
                # SES-verified sender identity. Must match the identity ARN
                # in the IAM policy above and must be verified in SES (and in
                # sandbox mode, the recipient must also be verified — self-
                # send is fine; for arbitrary recipients request prod access).
                "EMAIL_SENDER": "yanivbohbot5@gmail.com",
                "LOG_LEVEL": "INFO",
            },
        )

        CfnOutput(
            self,
            "RuntimeArn",
            value=self.runtime.agent_runtime_arn,
            export_name=f"{project}-{env_name}-runtime-arn",
        )
        CfnOutput(
            self,
            "MemoryId",
            value=self.memory.memory_id,
            export_name=f"{project}-{env_name}-memory-id",
        )
