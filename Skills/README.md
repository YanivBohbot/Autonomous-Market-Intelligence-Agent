# Skills used to build this project

This directory documents the skills used to develop the **Autonomous Market Intelligence Agent**,
organized by type. These are reference notes (what each skill is + how we actually used it on
this project), not copies of the plugin source.

Scope: only the skills we actually used. The full installed set is much larger.

## The recurring loop

Every subsystem (yfinance, filesystem, memory-store, playwright, durable-checkpointer,
agentcore-browser) followed the same workflow:

```
brainstorming → writing-plans → using-git-worktrees → test-driven-development
→ requesting-code-review → receiving-code-review → verification-before-completion
→ finishing-a-development-branch → memory
```

## Index

### process/  — the workflow backbone
- [brainstorming](process/brainstorming.md)
- [writing-plans](process/writing-plans.md)
- [executing-plans](process/executing-plans.md)
- [subagent-driven-development](process/subagent-driven-development.md)
- [test-driven-development](process/test-driven-development.md)
- [systematic-debugging](process/systematic-debugging.md)
- [using-git-worktrees](process/using-git-worktrees.md)
- [requesting-code-review](process/requesting-code-review.md)
- [receiving-code-review](process/receiving-code-review.md)
- [verification-before-completion](process/verification-before-completion.md)
- [finishing-a-development-branch](process/finishing-a-development-branch.md)

### aws/  — AWS design & deployment (aws-dev-toolkit plugin)
> These map the sections of `prod/SPEC.md` to the AWS skill that produces that kind
> of output. Unlike the feature specs, SPEC.md doesn't name skills inline, so these
> are reconstructed from the artifact structure + our deployment memory entries.
- [aws-plan](aws/aws-plan.md) — umbrella: discovery → design → security → cost → SCPs (incl. alternatives considered)
- [aws-architect](aws/aws-architect.md) — architecture + S3 storage design
- [security-review](aws/security-review.md)
- [iam](aws/iam.md)
- [cost-check](aws/cost-check.md)
- [lambda](aws/lambda.md)
- [observability](aws/observability.md)
- [agentcore](aws/agentcore.md) — Runtime + Gateway + Memory + Browser

### domain/  — other implementation / tooling skills
- [code-review](domain/code-review.md)

### supporting/
- [using-superpowers](supporting/using-superpowers.md)
- [memory-workflow](supporting/memory-workflow.md)
