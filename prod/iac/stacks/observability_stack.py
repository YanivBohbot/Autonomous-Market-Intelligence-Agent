"""ObservabilityStack — AWS Budgets alarms + CloudWatch alarms + SNS topic.

Per prod/SPEC.md §5.6: two Budgets thresholds at $50 and $150/mo against
the deploy account, scoped to resources tagged Project=mia. SNS topic
receives the notifications and emails the operator.

Also adds a CloudWatch alarm on Secrets Manager denied GetSecretValue
calls — security §4.6 follow-up.
"""

from __future__ import annotations

import os

from aws_cdk import Duration, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subs
from constructs import Construct


class MiaObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        alert_email: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.alerts = sns.Topic(
            self, "AlertsTopic",
            topic_name=f"{project}-alerts-{env_name}",
            display_name=f"{project} {env_name} alerts",
        )
        if alert_email:
            self.alerts.add_subscription(sns_subs.EmailSubscription(alert_email))

        # --- Cost guardrails ----------------------------------------------
        for threshold, label in ((50, "warn"), (150, "critical")):
            budgets.CfnBudget(
                self, f"Budget{threshold}",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name=f"{project}-{env_name}-{label}",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(
                        amount=threshold, unit="USD"
                    ),
                    cost_filters={
                        "TagKeyValue": [f"user:Project${project}"],
                    },
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN",
                            notification_type="ACTUAL",
                            threshold=80,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                subscription_type="SNS",
                                address=self.alerts.topic_arn,
                            )
                        ],
                    )
                ],
            )

        # --- Secrets-Manager denied-access alarm --------------------------
        denied_secret_access = cw.Metric(
            namespace="AWS/SecretsManager",
            metric_name="AccessDeniedException",
            statistic="Sum",
            period=Duration.minutes(5),
        )
        alarm = cw.Alarm(
            self, "SecretsAccessDeniedAlarm",
            alarm_name=f"{project}-{env_name}-secrets-access-denied",
            metric=denied_secret_access,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="Any denied Secrets Manager access from the Runtime / Lambdas",
        )
        alarm.add_alarm_action(cw_actions.SnsAction(self.alerts))
