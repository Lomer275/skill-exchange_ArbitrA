---
name: delivery-change
description: Use when preparing a change in an onboarded project and obtaining platform delivery-check evidence before release.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:delivery-change` and a skill named `delivery-change` exists in the project (`.claude/skills/delivery-change/SKILL.md`) or in the user's skills (`~/.claude/skills/delivery-change/SKILL.md`), stop: tell the user that their own `/delivery-change` takes precedence, and do nothing else.

# Prepare a delivery change

Read `.delivery/project.yaml`, project instructions and the pinned platform's
`delivery/targets.yaml`, schemas, intent parser and workflows. Concrete repositories,
environments, owners and credential references come from those files at runtime.
Stop on missing access, missing registration or an unsupported delivery path.
External writes follow the user's authorization; this skill does not grant it.

1. Work in an isolated checkout. Limit the source or patch to the requested target.
   Establish expected behavior, reversibility, affected data and external effects.
   Preserve a usable prior state; do not invent business rules or rollback guarantees.
2. Run the project test command and schema test. Prepare the PR against the final head
   SHA. Use the exact Russian intent heading and labels accepted by the pinned
   `delivery/intent.py` (heading prefixed by two hashes), with fields for what,
   why, decision and rollback. See the Russian skeleton in [README.md](README.md). Read their exact spelling from the parser; do not translate the labels
   in the actual PR. Fill every required field with concrete evidence.
3. For `.js`, include the parser's visual review field, explain the visible change,
   provide the stage link and obtain the required owner review. A green automated
   run does not prove that a user has reviewed the screen.
4. Let project CI dispatch `delivery-check.yml` with `repo`, final head `sha`, `pr`,
   `target`, `request_id`, platform repository and ref. Do not send a duplicate request
   if CI already sent one. Locate its run by the request id in `display_title`,
   following all API pages; the platform head SHA is not the project's source SHA.
5. Wait for completion and inspect the platform output and the corresponding
   `checks/<computed-key>.json` on `delivery-journal`. The key hashes
   `package_sha256|adapter_version|base_hash`. Inspect each required check's status,
   `output_sha256`, `output_path` and `run_url` using the target's policy for
   `not_available`. If a sandbox install created a journal row, inspect its latest
   state too. A check record need not have an apply row.
6. Report PR/head SHA, request id, platform run, package and base hashes, check record,
   actual outputs, visual evidence and unresolved requirements. Recheck after source
   or base changes. Merge and release only under the applicable review and authorization.

Stop on failed, cancelled, timed out or unknown outcomes. Cancelled requests may
have been displaced by another request for the target; inspect before requesting a retry.
Do not bypass CI, the guard or the platform using direct transport or an admin UI.
