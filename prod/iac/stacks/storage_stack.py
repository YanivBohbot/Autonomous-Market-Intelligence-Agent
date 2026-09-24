"""StorageStack — S3 buckets for the workspace and the static data set.

Two buckets per prod/SPEC.md §3.1:

- `mia-workspace`  — replaces local `data/workspace/`. Filesystem MCP Lambda
  reads/writes via S3 SDK. Versioning ON so accidental overwrites are recoverable.
- `mia-data`       — hosts the static SQLite CRM DB (`customers.db`) and the
  source PDFs used by RAG ingestion. customers.db is uploaded from the repo
  by a BucketDeployment on every deploy.

Both buckets are encrypted at rest with AWS-managed keys (default SSE-S3),
block all public access, and deny non-TLS requests via a bucket policy.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

# market-intelligence-agent/customers.db — seeded by create_db.py and
# committed; the sqlite-crm Lambda downloads it from the data bucket.
CRM_DB_FILE = Path(__file__).resolve().parents[3] / "market-intelligence-agent" / "customers.db"


class MiaStorageStack(Stack):
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
        auto_delete = env_name == "demo"

        self.workspace_bucket = self._make_bucket(
            "WorkspaceBucket",
            f"{project}-workspace-{self.account}",
            removal, auto_delete, versioned=True,
        )
        # The data bucket holds customers.db and the RAG source PDFs: always
        # RETAIN, never auto-delete, even in demo. A stack teardown (or a
        # construct replacement) must never wipe the data. The workspace
        # bucket only holds agent scratch output, so it follows env_name.
        self.data_bucket = self._make_bucket(
            "DataBucket",
            f"{project}-data-{self.account}",
            RemovalPolicy.RETAIN, False, versioned=True,
        )

        # Keep S3 in sync with git: before this, customers.db was copied to
        # the bucket by hand and could silently drift from the repo.
        # Stage the single file in its own dir so the asset doesn't walk the
        # whole app folder. prune=False: the bucket also holds RAG PDFs.
        staging = Path(tempfile.mkdtemp(prefix="crm-db-"))
        shutil.copy2(CRM_DB_FILE, staging / "customers.db")
        s3deploy.BucketDeployment(
            self, "CrmDbDeployment",
            sources=[s3deploy.Source.asset(str(staging))],
            destination_bucket=self.data_bucket,
            prune=False,
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
        removal: RemovalPolicy,
        auto_delete: bool,
        *,
        versioned: bool,
    ) -> s3.Bucket:
        return s3.Bucket(
            self, construct_id,
            bucket_name=bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,  # adds the aws:SecureTransport=false deny stmt
            versioned=versioned,
            removal_policy=removal,
            auto_delete_objects=auto_delete,
        )
