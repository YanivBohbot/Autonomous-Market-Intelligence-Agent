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
  SecretValue,
  Stack,
  aws_dynamodb as dynamodb,
  aws_iam as iam,
  aws_logs as logs,
  aws_s3 as s3,
  aws_secretsmanager as secretsmanager,
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

  /** JSON secret bundle: OpenAI, Pinecone, Tavily, and email-SMTP credentials. */
  public readonly apiKeysSecret: secretsmanager.Secret;

  /** CloudWatch Log Group surfaced for operator convenience. */
  public readonly logGroup: logs.LogGroup;

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

    // --- Phase 5: Secrets Manager + non-secret config + log group ---
    //
    // Single JSON bundle. The agent's bootstrap.py fetches at boot and
    // copies each key into os.environ before pydantic-settings runs.
    // Created with a placeholder; operator fills real values via the
    // Secrets Manager console after first deploy.
    //
    // RETAIN so a stack destroy doesn't wipe rotated keys.
    this.apiKeysSecret = new secretsmanager.Secret(this, 'ApiKeysSecret', {
      secretName: `${spec.name}/api-keys`,
      description: 'API keys for the Market Intelligence agent (fill via Console after deploy).',
      removalPolicy: RemovalPolicy.RETAIN,
      secretObjectValue: {
        OPENAI_API_KEY: SecretValue.unsafePlainText('REPLACE_ME'),
        PINECONE_API_KEY: SecretValue.unsafePlainText('REPLACE_ME'),
        TAVILY_API_KEY: SecretValue.unsafePlainText('REPLACE_ME'),
        EMAIL_PASSWORD: SecretValue.unsafePlainText('REPLACE_ME'),
      },
    });

    // CloudWatch log group for the runtime. AgentCore Runtime writes here
    // automatically once it knows the name; explicit so we can apply
    // retention + surface the name in CfnOutput.
    this.logGroup = new logs.LogGroup(this, 'RuntimeLogGroup', {
      logGroupName: `/aws/bedrock-agentcore/runtimes/${spec.name}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // Non-secret config that pydantic-settings needs. The voice keys
    // (LIVEKIT_*, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY) are required by the
    // shared Settings schema but unused by the agent runtime — give them
    // explicit dummy values so the agent boots without a NoneType crash.
    const nonSecretEnv: Record<string, string> = {
      OPENAI_MODEL: 'gpt-4o-mini',
      OPENAI_EMBEDDING_MODEL: 'text-embedding-3-small',
      PINECONE_INDEX_NAME: 'market-intel',
      EMAIL_SENDER: 'noreply@example.com',
      EMAIL_SMTP_SERVER: 'smtp.gmail.com',
      EMAIL_SMTP_PORT: '587',
      LOG_LEVEL: 'INFO',
      // Voice keys — unused by the agent runtime.
      LIVEKIT_URL: 'unused-in-prod-agent',
      LIVEKIT_API_KEY: 'unused-in-prod-agent',
      LIVEKIT_API_SECRET: 'unused-in-prod-agent',
      DEEPGRAM_API_KEY: 'unused-in-prod-agent',
      ELEVENLABS_API_KEY: 'unused-in-prod-agent',
    };

    for (const [, env] of this.application.environments) {
      // Inject secret ARN + non-secret config.
      env.runtime.addEnvironmentVariable(
        'API_KEYS_SECRET_ARN',
        this.apiKeysSecret.secretArn,
      );
      for (const [key, value] of Object.entries(nonSecretEnv)) {
        env.runtime.addEnvironmentVariable(key, value);
      }

      // IAM: GetSecretValue scoped to this secret only.
      env.runtime.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['secretsmanager:GetSecretValue'],
          resources: [this.apiKeysSecret.secretArn],
        }),
      );
    }

    new CfnOutput(this, 'ApiKeysSecretArn', {
      description: 'Secrets Manager ARN for the API key bundle — fill via Console',
      value: this.apiKeysSecret.secretArn,
    });
    new CfnOutput(this, 'LogGroupName', {
      description: 'CloudWatch Log Group for the runtime',
      value: this.logGroup.logGroupName,
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
