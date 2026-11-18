---
name: delivery-release
description: Use when verifying a merged delivery, reverting a journalled change, disabling its feature or recording an authorized emergency operation.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:delivery-release` and a skill named `delivery-release` exists in the project (`.claude/skills/delivery-release/SKILL.md`) or in the user's skills (`~/.claude/skills/delivery-release/SKILL.md`), stop: tell the user that their own `/delivery-release` takes precedence, and do nothing else.

# Verify or recover a delivery

Read `.delivery/project.yaml`, project instructions and the pinned platform's
`delivery/targets.yaml`, workflows, CLI and journal model. Resolve all concrete
repositories, environments, owners and credential references from those sources.
Record the version and commit SHA read. Missing access, unknown ownership, drift or
an unsupported executor is a stop; do not choose a similar transport.
This skill routes authorized operations and does not grant external write access.

## Verify the release

1. Classify code, configuration, data and external effects. Confirm the release window,
   prior working state and rollback limits. Use an isolated checkout for any changes.
   Require project checks and review on the final PR head; record the distinct merge
   SHA. Pending, skipped and cancelled are not successful test evidence.
2. Find the project CI request for that merge SHA, then locate the platform run by
   `request_id` in `display_title`, paginating workflow runs with a creation time bound.
   Follow the existing dispatch rather than duplicating it. Inspect all relevant jobs
   and steps; a successful no-op or unrelated platform SHA is not proof of installation.
3. Read `delivery-journal`: rows are append-only in `journal/YYYY-MM.jsonl`, by month
   of `opened_at`; the last occurrence of an `id` is its state. Match `request_id`,
   target, env, repo and source SHA. Inspect `status`, `operation`, `package_sha256`,
   `base_hash`, `hashes_after`, `reconciled`, `closed_at` and check evidence.
4. Compare `hashes_after` with current hashes from the approved executor or its
   reconciliation evidence, with the same file/block or workflow normalization as
   the adapter. If unavailable, mark hash verification incomplete. Inspect safe health
   evidence, logs and the expected functional checkpoint. Active checks need a safe
   object and authorization. Running containers, notifications and workflow success
   alone do not prove the expected effect.

## Recover through the platform

Use `gh workflow run delivery-release.yml --repo "$PLATFORM" --ref "$REF"`
with fields `op`, `target`, `env`, `row_id`, `reason`. Obtain platform and ref from
project configuration, and target/env and original row id from the journal and registry.
`op` is `revert` or `kill_switch`. The CLI equivalent inside that workflow is
`python -m delivery release --op ... --target ... --env ... --row-id ... --reason ...`;
it refuses execution outside the matching platform workflow.

Inspect the new run and journal row, then repeat hash, health and functional checks.
Revert uses the original row id as the adapter's undo run id. Kill switch requires
support in the original manifest. Neither operation guarantees restoration of database
state or external writes. Do not rerun an old deployment, cancel another run or switch
to direct server access as a substitute for recovery.

## Emergency journal entry

For a separately authorized manual operation, use the pinned platform checkout:

```bash
python -m delivery manual open --request-id "$REQUEST_ID" --target "$TARGET" \
  --env "$ENVIRONMENT" --what "$WHAT" --why "$WHY" --decision "$DECISION" \
  --actor "$ACTOR" --rollback "$ROLLBACK"
```

Supply `--base-hash` and `--expected-hashes` when known, and repo/SHA and a backup
reference where appropriate. This records intent; it does not execute the operation.
Confirm the journal push and latest `status=open`, then put only the returned row
`id` in the project's `.delivery/open_row`. The guard checks the remote journal and
blocks when it cannot verify it. Do not fabricate a row or disable the guard.

After the authorized action, verify its effect and close the entry:

```bash
python -m delivery manual close --row-id "$ROW_ID" --status "$STATUS" \
  --hashes-after "$HASHES_AFTER" --note "$NOTE"
```

Use observed `applied`, `failed`, `rolled_back` or `unknown`, and the actual JSON
hash map. Remove the local row marker only after confirming closure. An unknown
outcome remains unresolved and requires reconciliation, not an invented success.

CLI codes: zero means completed; two means gate refusal or deferred; three means
adapter failure with rollback; four means unknown; reconcile returns one for alarms.
The project wait helper returns only zero or one and does not preserve these codes.

## Report

Provide target/type/window, PR/head/merge SHA, request id, run URLs and correlation,
package/check evidence, latest journal row and hashes, relevant job/step outcomes,
commands with actual output, expected versus observed function, rollback and limitations.
Distinguish installed and accepted, incomplete acceptance, rolled back and refused.
Stop before unauthorized secret changes, destructive data operations, platform settings,
manual server actions or checks without a safe object. Never request secret values in chat.
