# code-review (and the /code-review command)

**Type:** Domain / tooling
**Plugin:** code-review

## What it is
Reviews a diff/PR for correctness bugs and reuse/simplification/efficiency cleanups at a
chosen effort level. `/code-review ultra` runs a deep multi-agent cloud review.

## How we used it on this project
The review step on the GitHub PRs (#1–#4) for the browser subsystem and earlier feature
merges. Pairs with the `requesting-code-review` process skill: that skill decides *when*
to review, this command/skill *performs* the diff review.
