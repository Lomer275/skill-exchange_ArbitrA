---
name: delivery-onboard
description: Use when connecting a project to a delivery platform with registered targets, project CI and a structural command guard.
---

## Step 0 — precedence check (mandatory)

If the user did not type `/team-skills:delivery-onboard` and a skill named `delivery-onboard` exists in the project (`.claude/skills/delivery-onboard/SKILL.md`) or in the user's skills (`~/.claude/skills/delivery-onboard/SKILL.md`), stop: tell the user that their own `/delivery-onboard` takes precedence, and do nothing else.

# Connect a project

Ask for the platform repository and the project owner. Read project instructions first.
This skill prepares a connection; external writes require authorization for that action.

1. Resolve a fixed platform version, preferably an immutable release tag supported by
   workflow dispatch. Record its commit SHA as evidence. Read `delivery/schema/`,
   `delivery/templates/`, `delivery/targets.yaml`, the workflow inputs and CLI at that
   version. Stop if the repository or required files cannot be read. Do not substitute
   another platform, transport or a locally installed skill's directory.
2. Ask the owner which registered targets, source paths, environments and adapters apply,
   and whether stage review is needed. Derive concrete values from the platform registry;
   do not invent target ownership, windows, credentials or destination permissions.
   For a new target, prepare a registration PR in the platform using its target schema
   and catalogue requirements. Open it only within granted authorization. Wait for it
   to merge, then pin a version containing the registration before dispatching anything.
3. Create `.delivery/project.yaml` with `platform.repo`, `platform.ref`, `owner`,
   `tests.check_names`, `stage_review` and `targets`. Use only schema-supported keys.
   File targets use `source`, `dest_prefix`, optional `blocks` and `kill_switch`;
   workflow targets use `patch`. Validate against the pinned project schema.
4. Copy `project.schema.json` into `.delivery/`. Copy `test_delivery_project.py` into
   the project's tests and `wait_result.py` and `claude_guard_hook.py` into `.delivery/`.
   Render `delivery-ci.yml` into the project's workflow directory: replace
   `{{TEST_COMMAND}}`, `{{CHECK_NAME}}` and `{{TARGETS}}` with the real test command,
   test job name and YAML target list. Include the schema test in the test command.
   `tests.check_names` must name the tests job, never the waiting delivery job.
   Preserve PR head checkout, separate jobs, hosted waiting, the platform dispatch
   token reference in the template, and every dispatch input. Read credential names
   from the template at runtime; never embed their values in files or reports.
5. Merge `claude_settings_snippet.json` into `.claude/settings.json`, preserving existing
   hooks and settings. Ensure the hook's Python has PyYAML and the project test
   environment has PyYAML, jsonschema and pytest. Do not create `.delivery/open_row`:
   only a confirmed emergency journal entry can supply its id.
6. Run the schema test and project tests, inspect the rendered YAML and unresolved
   template markers, and show the diff. Document platform ref and SHA, target ids,
   test check names, hook path, registration PR and any missing access. A later
   delivery check needs its own journal/check evidence; installation alone is not acceptance.

Stop on unavailable access, an unsupported adapter or ambiguous business rules.
Do not publish secrets, create platform settings or start a delivery to repair onboarding.
