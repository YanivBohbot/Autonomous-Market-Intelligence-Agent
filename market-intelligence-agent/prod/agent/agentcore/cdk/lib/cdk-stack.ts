import {
  AgentCoreApplication,
  AgentCoreMcp,
  type AgentCoreProjectSpec,
  type AgentCoreMcpSpec,
} from '@aws/agentcore-cdk';
import {
  CfnOutput,
  RemovalPolicy,
  Stack,
  aws_dynamodb as dynamodb,
  aws_iam as iam,
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

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { spec, mcpSpec, credentials } = props;

    // Create AgentCoreApplication with all agents
    this.application = new AgentCoreApplication(this, 'Application', {
      spec,
    });

    // Create AgentCoreMcp if there are gateways configured
    if (mcpSpec?.agentCoreGateways && mcpSpec.agentCoreGateways.length > 0) {
      new AgentCoreMcp(this, 'Mcp', {
        projectName: spec.name,
        mcpSpec,
        agentCoreApplication: this.application,
        credentials,
        projectTags: spec.tags,
      });
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
