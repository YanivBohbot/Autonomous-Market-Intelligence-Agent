import {
  AgentCoreApplication,
  AgentCoreMcp,
  type AgentCoreProjectSpec,
  type AgentCoreMcpSpec,
} from '@aws/agentcore-cdk';
import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  aws_dynamodb as dynamodb,
  aws_iam as iam,
  aws_s3 as s3,
  type StackProps,
} from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /**
   * The AgentCore project specification containing agents, memories, and credentials.
   */
  spec: AgentCoreProjectSpec;
  /**
   * The MCP specification containing gateways and servers.
   */
  mcpSpec?: AgentCoreMcpSpec;
  /**
   * Credential provider ARNs from deployed state, keyed by credential name.
   */
  credentials?: Record<string, { credentialProviderArn: string; clientSecretArn?: string }>;
}

/**
 * CDK Stack that deploys AgentCore infrastructure.
 *
 * This is a thin wrapper that instantiates L3 constructs.
 * All resource logic and outputs are contained within the L3 constructs.
 *
 * Phase 3 extension: also provisions a DynamoDB table for LangGraph
 * checkpoint persistence and wires it to the agent runtime via env var +
 * IAM grant. The agent picks it up at runtime via `DDB_CHECKPOINT_TABLE`.
 */
export class AgentCoreStack extends Stack {
  /** The AgentCore application containing all agent environments */
  public readonly application: AgentCoreApplication;

  /** DynamoDB table that stores LangGraph checkpoints (one per thread_id). */
  public readonly checkpointTable: dynamodb.Table;

  /** S3 bucket holding screenshots taken by the AgentCore Browser tool. */
  public readonly screenshotBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { spec, mcpSpec, credentials } = props;

    // Create AgentCoreApplication with all agents
    this.application = new AgentCoreApplication(this, 'Application', {
      spec,
    });

    // Create AgentCoreMcp if there are gateways configured.
    //
    // The L3 construct auto-wires gateway URLs into every runtime as
    // `AGENTCORE_GATEWAY_{NAME}_URL`. For our `market-gw` gateway that's
    // `AGENTCORE_GATEWAY_MARKET_GW_URL`. We additionally publish a generic
    // `GATEWAY_URL` env var pointing at the same endpoint so the Python
    // registry can read a single, stable name (see registry.py).
    let mcp: AgentCoreMcp | undefined;
    if (mcpSpec?.agentCoreGateways && mcpSpec.agentCoreGateways.length > 0) {
      mcp = new AgentCoreMcp(this, 'Mcp', {
        projectName: spec.name,
        mcpSpec,
        agentCoreApplication: this.application,
        credentials,
        projectTags: spec.tags,
      });

      // Find the primary gateway (`market-gw`) and inject GATEWAY_URL.
      const primary = mcp.gateways.get('market-gw');
      if (primary) {
        for (const [, env] of this.application.environments) {
          env.runtime.addEnvironmentVariable('GATEWAY_URL', primary.attrGatewayUrl);
        }
      }
    }

    // --- Phase 3: LangGraph checkpoint store (DynamoDB) ---
    //
    // Schema follows the official AWS guide for `langgraph-checkpoint-aws`:
    // composite key (PK, SK) with TTL on the `ttl` attribute. PITR + SSE on.
    // Billing is pay-per-request so the table costs ~$0 at zero traffic.
    // RETAIN on delete so checkpoint history isn't wiped if the stack is torn
    // down accidentally.
    this.checkpointTable = new dynamodb.Table(this, 'CheckpointTable', {
      tableName: `${spec.name}-langgraph-checkpoints`,
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // Wire the table to every agent runtime in the project.
    // Currently there's one runtime (`agent`), but iterating future-proofs
    // multi-runtime projects.
    for (const [agentName, env] of this.application.environments) {
      env.runtime.addEnvironmentVariable(
        'DDB_CHECKPOINT_TABLE',
        this.checkpointTable.tableName,
      );
      env.runtime.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'dynamodb:GetItem',
            'dynamodb:PutItem',
            'dynamodb:Query',
            'dynamodb:BatchGetItem',
            'dynamodb:BatchWriteItem',
          ],
          resources: [this.checkpointTable.tableArn],
        }),
      );
      new CfnOutput(this, `CheckpointTableWiredTo${agentName}`, {
        description: `Checkpoint table name passed to runtime '${agentName}'`,
        value: this.checkpointTable.tableName,
      });
    }

    // --- Phase 4b: AgentCore Browser screenshots bucket + IAM ---
    //
    // Per-call sessions upload PNGs to this bucket; the tool returns a
    // 1-hour pre-signed URL to the LLM. Lifecycle rule deletes objects
    // after 30 days so the bucket doesn't grow unbounded.
    this.screenshotBucket = new s3.Bucket(this, 'ScreenshotBucket', {
      bucketName: `${spec.name}-screenshots-${this.account}-${this.region}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
      lifecycleRules: [{ expiration: Duration.days(30) }],
    });

    for (const [, env] of this.application.environments) {
      // Tell the runtime which bucket to upload to + flip the import gate.
      env.runtime.addEnvironmentVariable(
        'SCREENSHOT_BUCKET',
        this.screenshotBucket.bucketName,
      );
      env.runtime.addEnvironmentVariable('BROWSER_ENABLED', 'true');

      // S3 write on the screenshot bucket only.
      env.runtime.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['s3:PutObject', 's3:GetObject'],
          resources: [this.screenshotBucket.arnForObjects('*')],
        }),
      );

      // AgentCore Browser session management. Scoped to browser/* in this
      // account/region (we use the built-in browser, not a custom one).
      env.runtime.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'bedrock-agentcore:StartBrowserSession',
            'bedrock-agentcore:StopBrowserSession',
            'bedrock-agentcore:GetBrowserSession',
            'bedrock-agentcore:ConnectBrowserAutomationStream',
          ],
          resources: [
            `arn:aws:bedrock-agentcore:${this.region}:${this.account}:browser/*`,
          ],
        }),
      );
    }

    new CfnOutput(this, 'ScreenshotBucketName', {
      description: 'S3 bucket for AgentCore Browser screenshots',
      value: this.screenshotBucket.bucketName,
    });

    // Stack-level outputs
    new CfnOutput(this, 'StackNameOutput', {
      description: 'Name of the CloudFormation Stack',
      value: this.stackName,
    });
    new CfnOutput(this, 'CheckpointTableArn', {
      description: 'ARN of the LangGraph checkpoint DynamoDB table',
      value: this.checkpointTable.tableArn,
    });
  }
}
