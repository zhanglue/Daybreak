# Repository Instructions

## Language

- Communicate with the user in Chinese.
- Write all tracked file content in English, including documentation, code comments, docstrings, prompts, and committed examples.
- Write Git commit messages in English.
- The language of generated, untracked personal reports is a separate product decision; do not infer it from the repository language.

## Start of a task

- Read `README.md`, `docs/roadmap.md`, and the relevant implementation plan.
- Check the branch and working tree; preserve existing user changes.
- Identify the current task from the user's request. Do not independently advance to another milestone.

## Scope and implementation

- Use the existing Conda environment named `daybreak` for development and checks. `config/environment.yaml` and `config/requirements.txt` define its Python and dependency versions; do not create a separate virtual environment.
- Treat Daybreak as a local MCP server. Define the initial Skills workflow and draft tool contracts before implementation; refine them after Garmin access and data discovery.
- Codex must obtain Garmin data through Daybreak MCP tools, never through direct Garmin requests or access to Garmin credentials.
- Skills define tool-use and analysis workflows; the MCP server owns Garmin access and data responses. A separate manual or scheduled runner starts Codex; the MCP server must not recursively launch Codex.
- Use `httpx` for the general-purpose asynchronous HTTP client. Keep Garmin authentication and endpoint behavior outside the generic transport layer.
- Before explicitly raising an exception, log the error with the shared `Logger.ERROR`. Keep error logs free of credentials and personal data.
- Within classes, declare attributes first, then public class/static methods, public instance methods and properties, special methods (such as `__new__` and `__init__`), and finally underscore-prefixed internal methods, including internal class/static methods.
- Call class/static methods through the explicit class name (for example, `GarminConnectClient.get_client()`), not through `self`. Use `cls` inside class methods when subclass dispatch is intended.
- Use a local Codex command with predefined Skills and the Daybreak MCP connection. Verify the installed CLI, Skills discovery, MCP configuration, and unattended behavior before implementing invocation.
- Record additional requirements as follow-up work. Discuss material scope or architecture changes before implementing them.
- Keep these instructions concise; store task progress in the implementation plan.

## Verification and handoff

- Run checks appropriate to the change and report any verification limits.
- Update documentation when behavior, interfaces, or development commands change.
- Mark tasks complete only when their acceptance criteria are satisfied. Do not store an active branch pointer in shared planning documents.
- At handoff, summarize changes, verification, remaining issues, and the suggested next step.

## Git and local data

- Create short-lived task branches from the latest `main` when tasks begin; do not pre-create all branches.
- Stage only files relevant to the task. Do not merge or push without a user request.
- Do not read or disclose secrets or personal health data without task-specific authorization. Never commit credentials, tokens, or personal health data.
- Use synthetic or explicitly approved sanitized fixtures for committed examples and tests.
