"""McpLambdasStack — three Lambda functions, one per MCP tool server.

Per prod/SPEC.md §3.1 + §4.1: three per-function execution roles (not one
shared role) to limit blast radius across MCP tools. yfinance ships as a
container Lambda because the yfinance/pandas dep stack exceeds the 250 MB
zip limit; filesystem and sqlite-crm ship as plain zip functions because
they only need boto3 which is built into the Python runtime.

Lambdas are stateless and have no AWS dependencies beyond their own bucket
access — wiring to AgentCore Gateway happens in MiaGatewayStack.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

LAMBDAS_DIR = Path(__file__).resolve().parents[2] / "lambdas"


class MiaMcpLambdasStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        workspace_bucket: s3.IBucket,
        data_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.yfinance_fn = self._make_yfinance_lambda(project, env_name)
        self.filesystem_fn = self._make_filesystem_lambda(project, env_name, workspace_bucket)
        self.sqlite_crm_fn = self._make_sqlite_crm_lambda(project, env_name, data_bucket)

        for label, fn in (
            ("Yfinance", self.yfinance_fn),
            ("Filesystem", self.filesystem_fn),
            ("SqliteCrm", self.sqlite_crm_fn),
        ):
            CfnOutput(
                self, f"{label}FnArn",
                value=fn.function_arn,
                export_name=f"{project}-{env_name}-mcp-{label.lower()}-arn",
            )

    # --- yfinance (container Lambda — heavy deps) -----------------------

    def _make_yfinance_lambda(self, project: str, env_name: str) -> _lambda.Function:
        role = iam.Role(
            self, "YfinanceRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description=f"{project}-{env_name} yfinance MCP Lambda execution role",
        )
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )
        return _lambda.DockerImageFunction(
            self, "YfinanceFn",
            function_name=f"{project}-mcp-yfinance-{env_name}",
            code=_lambda.DockerImageCode.from_image_asset(
                str(LAMBDAS_DIR / "yfinance"),
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.seconds(30),
            role=role,
            log_retention=logs.RetentionDays.ONE_MONTH,
        )

    # --- filesystem (zip Lambda — boto3 only) ---------------------------

    def _make_filesystem_lambda(
        self,
        project: str,
        env_name: str,
        workspace_bucket: s3.IBucket,
    ) -> _lambda.Function:
        role = iam.Role(
            self, "FilesystemRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description=f"{project}-{env_name} filesystem MCP Lambda execution role",
        )
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )
        workspace_bucket.grant_read_write(role)

        return _lambda.Function(
            self, "FilesystemFn",
            function_name=f"{project}-mcp-filesystem-{env_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(str(LAMBDAS_DIR / "filesystem")),
            memory_size=256,
            timeout=Duration.seconds(15),
            role=role,
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "WORKSPACE_S3_BUCKET": workspace_bucket.bucket_name,
                "LOG_LEVEL": "INFO",
            },
        )

    # --- sqlite-crm (zip Lambda — stdlib + boto3) -----------------------

    def _make_sqlite_crm_lambda(
        self,
        project: str,
        env_name: str,
        data_bucket: s3.IBucket,
    ) -> _lambda.Function:
        role = iam.Role(
            self, "SqliteCrmRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description=f"{project}-{env_name} sqlite-crm MCP Lambda execution role",
        )
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )
        # READ-ONLY by design — no PutObject grant.
        data_bucket.grant_read(role, "customers.db")

        return _lambda.Function(
            self, "SqliteCrmFn",
            function_name=f"{project}-mcp-sqlite-crm-{env_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(str(LAMBDAS_DIR / "sqlite_crm")),
            memory_size=256,
            timeout=Duration.seconds(15),
            role=role,
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "DATA_S3_BUCKET": data_bucket.bucket_name,
                "CRM_DB_KEY": "customers.db",
                "LOG_LEVEL": "INFO",
            },
        )
