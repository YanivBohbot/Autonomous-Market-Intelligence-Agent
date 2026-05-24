"""StorageStack — S3 buckets for the workspace and the static data set.

Two buckets per prod/SPEC.md §3.1:

- `mia-workspace`  — replaces local `data/workspace/`. Filesystem MCP Lambda
  reads/writes via S3 SDK. Versioning ON so accidental overwrites are recoverable.
- `mia-data`       — hosts the static SQLite CRM DB (`customers.db`) and the
  source PDFs used by RAG ingestion.

Both buckets are encrypted with the shared CMK from MiaIdentityStack, block all
public access, and deny non-TLS requests via a bucket policy (security §4.2).
"""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct


class MiaStorageStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        kms_key: kms.IKey,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        removal = RemovalPolicy.DESTROY if env_name == "demo" else RemovalPolicy.RETAIN
        auto_delete = env_name == "demo"

        self.workspace_bucket = self._make_bucket(
            "WorkspaceBucket",
            f"{project}-workspace-{self.account}",
            kms_key, removal, auto_delete, versioned=True,
        )
        self.data_bucket = self._make_bucket(
            "DataBucket",
            f"{project}-data-{self.account}",
            kms_key, removal, auto_delete, versioned=True,
        )

        CfnOutput(self, "WorkspaceBucketName",
                  value=self.workspace_bucket.bucket_name,
                  export_name=f"{project}-{env_name}-workspace-bucket")
        CfnOutput(self, "DataBucketName",
                  value=self.data_bucket.bucket_name,
                  export_name=f"{project}-{env_name}-data-bucket")

    def _make_bucket(
        self,
        construct_id: str,
        bucket_name: str,
        kms_key: kms.IKey,
        removal: RemovalPolicy,
        auto_delete: bool,
        *,
        versioned: bool,
    ) -> s3.Bucket:
        bucket = s3.Bucket(
            self, construct_id,
            bucket_name=bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,  # adds the aws:SecureTransport=false deny stmt
            versioned=versioned,
            removal_policy=removal,
            auto_delete_objects=auto_delete,
        )
        # Belt-and-braces: explicitly deny PutObject without SSE-KMS using our key.
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:PutObject"],
                resources=[bucket.arn_for_objects("*")],
                conditions={
                    "StringNotEquals": {
                        "s3:x-amz-server-side-encryption": "aws:kms"
                    }
                },
            )
        )
        return bucket
