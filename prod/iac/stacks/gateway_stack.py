"""GatewayStack — AgentCore Gateway with three Lambda targets.

One unified MCP-over-HTTPS URL fronts all three tool Lambdas. Tool schemas
live next to the handler code in `prod/lambdas/<name>/tool_schema.json` so
the schema is reviewed alongside the implementation.

The default authorizer is a CDK-managed Cognito user pool — fine for a
demo where the agent (running in AgentCore Runtime) is the only client.
The Runtime stack will be granted invoke permissions on this gateway.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_lambda as _lambda
from constructs import Construct

LAMBDAS_DIR = Path(__file__).resolve().parents[2] / "lambdas"


class MiaGatewayStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        yfinance_fn: _lambda.IFunction,
        filesystem_fn: _lambda.IFunction,
        sqlite_crm_fn: _lambda.IFunction,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.gateway = agentcore.Gateway(
            self, "MiaGateway",
            gateway_name=f"{project}-gateway-{env_name}",
            description="MIA MCP gateway — yfinance, filesystem, sqlite-crm",
        )

        agentcore.GatewayTarget.for_lambda(
            self, "YfinanceTarget",
            gateway=self.gateway,
            gateway_target_name="yfinance",
            description="Stock ticker info, price history, news (yfinance)",
            lambda_function=yfinance_fn,
            tool_schema=agentcore.ToolSchema.from_local_asset(
                str(LAMBDAS_DIR / "yfinance" / "tool_schema.json")
            ),
        )
        agentcore.GatewayTarget.for_lambda(
            self, "FilesystemTarget",
            gateway=self.gateway,
            gateway_target_name="filesystem",
            description="Read / list / write text files in the agent workspace (S3-backed)",
            lambda_function=filesystem_fn,
            tool_schema=agentcore.ToolSchema.from_local_asset(
                str(LAMBDAS_DIR / "filesystem" / "tool_schema.json")
            ),
        )
        agentcore.GatewayTarget.for_lambda(
            self, "SqliteCrmTarget",
            gateway=self.gateway,
            gateway_target_name="sqlite-crm",
            description="Read-only SQL queries against the customers DB",
            lambda_function=sqlite_crm_fn,
            tool_schema=agentcore.ToolSchema.from_local_asset(
                str(LAMBDAS_DIR / "sqlite_crm" / "tool_schema.json")
            ),
        )

        CfnOutput(
            self, "GatewayArn",
            value=self.gateway.gateway_arn,
            export_name=f"{project}-{env_name}-gateway-arn",
        )
        # URL is optional on the construct (populated after deploy). The
        # Runtime container reads it from an env var sourced from this output.
        CfnOutput(
            self, "GatewayUrl",
            value=self.gateway.gateway_url or "<populated-after-deploy>",
            export_name=f"{project}-{env_name}-gateway-url",
        )
