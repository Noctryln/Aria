# Aria

Aria is a terminal-native AI coding agent built for real workspace execution, not just chat completion. It combines a Textual-based operator UI, a dual-backend LLM runtime (`llama.cpp` local + Google GenAI cloud), a structured XML-like tool protocol, live process streaming, GitHub automation, syntax validation, and production-oriented guardrails around file and shell operations.

This repository is the modularized package layout of Aria. The original monolith has been split into clear runtime layers so the system is easier to extend, audit, and ship.

Aria is intentionally Indonesian-first. The UX copy, speech input flow, and system prompt are optimized for Bahasa Indonesia, while the internal architecture is conventional enough for broader engineering use.

## What Aria Actually Does

Aria is not a generic TUI chatbot. It is an operator-facing coding runtime with:

- Local inference through `llama-cpp-python`, including optional LoRA attachment.
- Cloud inference through Google GenAI chat sessions with explicit rate limiting and retry behavior.
- Structured tool calling via XML-like tags such as `<read>`, `<edit>`, `<write>`, `<check_syntax>`, `<run_cmd>`, `<github_pr>`, and more.
- A live Textual UI that shows thinking state, streaming response rendering, tool execution state, shell output, status bars, and permission prompts.
- Workspace-bounded file operations with path checks against the current launch directory.
- Interactive shell execution with streamed stdout and stdin forwarding back through the same chat input box.
- GitHub device login plus issue / PR / Actions / repository / file / search workflows.
- Reverse image search and anime scene lookup from tool calls.
- Voice input through `SpeechRecognition`.
- Branch snapshots of conversational state and file diffs created during write/edit operations.

## Why This Architecture Exists

Aria has two jobs at the same time:

1. Behave like an assistant with context, memory, and streaming output.
2. Behave like an execution engine that can inspect, modify, validate, and operate on a real codebase.

That split is visible in the codebase:

- `ui/` owns rendering and operator interaction.
- `agent/` owns the chat submission loop and orchestration.
- `llm/` owns backend-specific model behavior.
- `tools/` owns parsing, extraction, and execution of tool tags.
- `integrations/` owns external services such as GitHub and web search.
- `core/` owns configuration, constants, and runtime defaults.
- `utils/` holds shared helper mixins and pure utility logic.

The result is a system that can stream tokens like a chat app, but also act like a constrained IDE agent.

## Feature Highlights

### Operator UI

- Textual TUI with a persistent chat log, input panel, status bar, loading bar, and permission dialog.
- Streaming assistant output with animated typing behavior.
- Separate thinking block for local reasoning traces when enabled.
- Rich markdown-ish rendering for headings, quotes, inline code, fenced code blocks, lists, tool boxes, and markdown tables.
- Context-remaining status bar tied to the active backend context window.
- Command suggestions for slash commands while typing.
- Clipboard copy support for selected text.
- Dynamic banner rendered from `aria/assets/banner.png` into terminal braille-colored output via Pillow.

### Runtime and Agent Behavior

- Dual backend runtime with hot reload between local and cloud mode.
- Planning-mode injection for heuristically complex requests before tool execution.
- Automatic self-correction loop after failed tool execution by feeding tool output back into the model as system observation.
- Explicit generation interruption support through `Esc`.
- Farewell sequence generation on clean exit, including streaming final message rendering and session metrics.

### Workspace and Tooling

- File listing, file discovery, workspace search, read, write, edit, mkdir, rm.
- Multi-language syntax checking for Python, JavaScript, TypeScript, JSON, YAML, PHP, Ruby, Bash, PowerShell, Lua, Java, Go, Rust, C/C++, Swift, Kotlin, R, and XML-like formats.
- Live shell execution with streamed output and interactive stdin handoff.
- Web fetch + Tavily search.
- Reverse image search via SerpApi-backed Google Lens flow.
- Anime screenshot lookup via `trace.moe` with AniList title resolution.
- GitHub issue, PR, Actions, repository, file, and global search tooling.

### Safety and Control Surface

- Tool execution permission gate with `Allow once`, `Always allow session`, and `Deny`.
- Workspace path restriction enforced against the launch directory for local file operations.
- Sequential tool execution stops on error.
- Tool boxes in the UI show running / success / error state.
- File writes and edits generate diff previews and are snapshotted into branch history.

## Repository Layout

```text
project-root/
|-- aria.py
|-- aria.cmd
|-- config.json
|-- pyproject.toml
|-- requirements.txt
|-- README.md
|
`-- aria/
    |-- __init__.py
    |-- app/
    |   |-- __init__.py
    |   |-- lifecycle.py
    |   `-- main.py
    |-- agent/
    |   |-- __init__.py
    |   |-- agent.py
    |   |-- memory.py
    |   `-- planner.py
    |-- assets/
    |   `-- banner.png
    |-- core/
    |   |-- __init__.py
    |   |-- config.py
    |   |-- constants.py
    |   |-- paths.py
    |   `-- runtime.py
    |-- integrations/
    |   |-- __init__.py
    |   |-- github.py
    |   `-- web_search.py
    |-- llm/
    |   |-- __init__.py
    |   |-- base.py
    |   |-- cloud.py
    |   |-- local.py
    |   |-- rate_limit.py
    |   `-- stream.py
    |-- tools/
    |   |-- __init__.py
    |   |-- executor.py
    |   |-- parser.py
    |   `-- registry.py
    |-- ui/
    |   |-- __init__.py
    |   |-- app.py
    |   |-- rendering.py
    |   `-- widgets/
    |       |-- __init__.py
    |       |-- ai_response.py
    |       |-- banner.py
    |       |-- chat_input.py
    |       `-- think_block.py
    `-- utils/
        |-- __init__.py
        |-- system.py
        |-- text.py
        `-- time.py
```

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `aria/app/main.py` | Entry bootstrap, backend initialization, app lifecycle loop, reload behavior, farewell rendering. |
| `aria/app/lifecycle.py` | Exit workflow, branch snapshot management, debug boxes, context reset, farewell prewarm/stream. |
| `aria/agent/agent.py` | Submission flow from user input to LLM stream to tool execution loop. |
| `aria/llm/base.py` | Unified runtime object composing local, cloud, stream, and rate-limit mixins. |
| `aria/llm/local.py` | `llama.cpp` initialization, LoRA injection, abort callback wiring. |
| `aria/llm/cloud.py` | Google GenAI chat session creation, chunk extraction, cloud stream orchestration, image upload support. |
| `aria/llm/stream.py` | Message assembly, history trimming, local/cloud stream adapters, standalone inference helpers. |
| `aria/llm/rate_limit.py` | Minimum-interval and per-minute throttling for cloud requests. |
| `aria/tools/registry.py` | Tool tag discovery from model text while ignoring fenced/inline code. |
| `aria/tools/parser.py` | Regex-based tool parsing helpers and tool-tag stripping utilities. |
| `aria/tools/executor.py` | Concrete execution engine for all tool tags, diff generation, shell orchestration, syntax checking. |
| `aria/integrations/github.py` | GitHub device OAuth login flow and token persistence. |
| `aria/integrations/web_search.py` | Tavily-backed web search helper. |
| `aria/ui/app.py` | Textual application shell, bindings, slash commands, input handling, permission dialog, streaming UI updates. |
| `aria/ui/widgets/ai_response.py` | Incremental assistant renderer for text, tool UI, code fences, markdown tables, and thinking placeholders. |
| `aria/ui/widgets/chat_input.py` | Message submission, multi-line editing, attachment marker generation from pasted paths/text. |
| `aria/ui/widgets/banner.py` | Startup banner renderer from image asset to terminal glyphs. |
| `aria/core/config.py` | Config load/save with default normalization. |
| `aria/core/constants.py` | System prompts and persona/tool instruction contract. |
| `aria/core/paths.py` | Workspace paths, asset paths, default model path, config location. |
| `aria/core/runtime.py` | Context defaults, temperature/top-p defaults, batch sizes, cloud throttling constants. |
| `aria/utils/system.py` | Console title updates and speech-recognition orchestration. |
| `aria/utils/text.py` | Tool-status decoration and shared regex helpers. |

`aria/agent/memory.py` and `aria/agent/planner.py` currently remain reserved extension points. They are present in the package layout but do not yet carry active runtime logic.

## Runtime Flow

At a high level, Aria runs this loop:

1. Load config and initialize the selected backend.
2. Start the Textual UI.
3. Accept user input or slash command.
4. Convert attachments into model-visible markers when needed.
5. Stream the model response.
6. Detect tool tags emitted by the model.
7. Ask the operator for permission if tool execution is not session-approved.
8. Execute tools sequentially and update the UI live.
9. Feed tool results back into the model as `<system_observation>`.
10. Repeat until the response is complete or the user interrupts.

This gives Aria an execution loop closer to an IDE agent than a traditional chat session.

## Installation

### Python

`pyproject.toml` requires Python `>=3.10`.

The launcher is Windows-first and expects a local virtual environment.

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Runtime Dependencies

Main Python dependencies currently declared in `requirements.txt`:

- `SpeechRecognition`
- `textual`
- `rich`
- `llama-cpp-python`
- `google-genai`
- `requests`
- `PyGithub`
- `Pillow`
- `PyYAML`
- `tika`
- `PyAudio`

### Optional External Toolchains

`<check_syntax>` delegates to native toolchains where appropriate. Install the tools you actually plan to validate:

- `node` for `.js`
- `tsc` for `.ts/.tsx`
- `php`
- `ruby`
- `bash`
- PowerShell
- `luac`
- `javac`
- `gofmt`
- `rustc`
- `gcc` / `g++`
- `swiftc`
- `kotlinc`
- `Rscript`

`tika` may require a Java runtime for document extraction fallback.

## Configuration

Aria persists runtime configuration in `config.json`.

```json
{
  "backend": "local",
  "local_model_path": "C:\\path\\to\\model.gguf",
  "lora_adapter_path": "",
  "google_api_key": "",
  "cloud_model": "gemma-4-26b-a4b-it",
  "serpapi_key": "",
  "github_oauth_token": "",
  "github_client_id": ""
}
```

### Config Fields

| Key | Purpose |
| --- | --- |
| `backend` | `local` or `cloud`. |
| `local_model_path` | Filesystem path to the GGUF model used by `llama.cpp`. |
| `lora_adapter_path` | Optional LoRA adapter path loaded into the local model. |
| `google_api_key` | Google AI Studio / GenAI API key for cloud mode. |
| `cloud_model` | Cloud model name used for Google GenAI chat sessions. |
| `serpapi_key` | API key used by reverse image search with SerpApi. |
| `github_oauth_token` | Populated after successful GitHub device login. |
| `github_client_id` | Required to initiate GitHub device OAuth flow. |

### Additional Secrets and Runtime Notes

- `GOOGLE_API_KEY` can be used as an environment fallback for cloud mode.
- Tavily search currently reads `TAVILY_API_KEY` from `aria/core/runtime.py`.
- The default local model path is derived from `models/Qwen3-4B/Qwen3-4B.gguf` under the project root.

## Running Aria

### Windows Launcher

```powershell
.\aria.cmd
```

### Direct Python Entry

```powershell
venv\Scripts\python.exe .\aria.py
```

`aria.py` remains the entry point and delegates directly into `aria.app.main.main()`.

## Keyboard and Slash Commands

### Core UI Bindings

- `Enter`: submit message
- `Shift+Enter`: insert newline
- `Ctrl+N`: alternate newline
- `Up` / `Down`: navigate slash-command suggestions
- `Ctrl+C`: copy selected input text
- `Esc`: interrupt generation
- `Ctrl+Q`: exit Aria

### Slash Commands

| Command | Behavior |
| --- | --- |
| `/speech` | Start microphone capture and speech-to-text recognition. |
| `/think` | Toggle local thinking display. Cloud mode ignores this. |
| `/debug` | Toggle cloud debug panels and current session context visibility. |
| `/lora <path/off>` | Attach or disable a LoRA adapter, then hot-reload local mode. |
| `/local` | Switch to the local backend and reload. |
| `/cloud` | Switch to the cloud backend and reload. |
| `/github login` | Start GitHub device OAuth flow. |
| `/clear` | Clear the chat log UI. |
| `/reset` | Reset conversation history and token counters. |
| `/branch` | Show stored branch snapshots from write/edit activity. |
| `/restore <id>` | Restore a prior conversation snapshot. |
| `/quit` | Clean exit with farewell flow. |

## Attachment Handling

The input widget performs lightweight attachment transformation when you paste content:

- Pasting an image path inserts `[Image-N]` and passes a structured image note to the model.
- Pasting a regular file path inserts `[File-N]` and inlines file content when readable.
- Pasting long text snippets inserts `[N-lines]` and stores the original text separately.

This keeps the UI readable while still giving the model access to the underlying data.

## Local and Cloud Backends

### Local Mode

Local mode is powered by `llama-cpp-python` and exposes:

- explicit context sizing
- explicit thread, batch, and ubatch tuning
- `flash_attn=True`
- optional LoRA path injection
- C-level abort callback installation for responsive interruption

History is sent directly through the local chat-completion API and trimmed when it exceeds 80% of the active context window.

### Cloud Mode

Cloud mode uses Google GenAI chat sessions and adds:

- system-instruction aware session creation
- high thinking configuration
- explicit per-minute and minimum-interval request throttling
- retry handling for quota / `429` style failures
- debug hooks for request/session visibility
- automatic upload of local image paths referenced in the user message

Cloud mode keeps a persistent cloud chat session and only sends the latest user turn through the session interface while preserving server-side context.

## Tool Protocol

Aria's execution model is driven by XML-like tool tags produced by the model. Examples:

```xml
<read>src/main.py</read>
<check_syntax file="src/main.py"></check_syntax>
<run_cmd timeout="60">pytest -q</run_cmd>
<github_pr repo="owner/repo" action="get_diff" number="42"></github_pr>
```

The parser deliberately ignores tool-looking text inside inline code and fenced code blocks, which reduces accidental execution from explanatory examples.

### Tool Categories

#### Workspace

- `ls`
- `find_file`
- `read`
- `search_workspace`
- `mkdir`
- `rm`

#### Editing and Validation

- `write`
- `edit`
- `check_syntax`

#### Web and External Data

- `fetch_url`
- `web_search`
- `search_image`

#### GitHub

- `github_issue`
- `github_pr`
- `github_actions`
- `github_repo`
- `github_file`
- `github_search`

#### Process Execution

- `run_cmd`

## Tool Execution Model

Tool execution is intentionally opinionated:

- execution is sequential
- the sequence stops on the first tool error
- UI status is updated live as tools move through running / success / error states
- tool results are re-injected into the model as `<system_observation>`
- failed tool results trigger a self-correction hint instructing the model to try another strategy

For file mutation operations:

- `write` and `edit` snapshot the original file state
- unified diffs are computed
- compact diff previews are shown in the UI
- branch snapshots are created for the turn

For shell execution:

- commands are started with `shell=False`
- stdout is streamed live into the UI
- the input box becomes stdin for the active process
- a hard kill timer is enforced

## Branch Snapshots

Aria stores lightweight branch snapshots every time a write/edit tool run generates tracked changes.

A branch snapshot contains:

- a snapshot id
- label and timestamp
- conversation history copy
- pre-edit file snapshots
- turn-level diff previews

Important: `/restore <id>` restores conversation history only. It does not revert files on disk. That behavior is explicit in the current implementation and should be understood before using branch restore as a recovery mechanism.

## Rendering System

The assistant renderer in `aria/ui/widgets/ai_response.py` is more than plain markdown passthrough. It handles:

- fenced code blocks
- inline code highlighting
- headings
- block quotes
- numbered and bulleted lists
- system observation panels
- tool execution panels
- animated thinking placeholders
- animated cloud response reveal
- markdown table parsing with Rich table rendering

This is why Aria can present tool traces and structured output in a terminal without collapsing into raw token text.

## Speech and Input Capture

Voice input is available through `/speech` and currently uses:

- `SpeechRecognition`
- `PyAudio`
- Google speech recognition backend with `id-ID`

The microphone path is optional. If you never use `/speech`, the rest of Aria remains usable without voice interaction.

## GitHub Automation

GitHub support is operator-grade rather than superficial:

- device OAuth flow for interactive terminal login
- issue listing / creation / comment / labeling / close
- PR listing / diff fetch / review / approve / merge / close
- Actions run listing and log link retrieval
- repo list / create / fork / info / branch creation / delete
- remote file read / write / delete without a local clone
- global code and repository search

This enables Aria to operate directly against GitHub-hosted repos from the same TUI session.

## Production Notes

This codebase is optimized for operator control and execution visibility, not for abstract framework purity.

That means a few deliberate tradeoffs:

- The system prompt is strong, explicit, and operationally opinionated.
- The runtime is Windows-first, even though some parts are cross-platform aware.
- Tool execution is broad by design, but still bounded by launch-directory checks and permission prompts.
- Cloud integrations and reverse image flows rely on third-party APIs and configured credentials.
- Some extension modules such as `memory.py` and `planner.py` are kept as reserved structure for future growth.

## Known Constraints

- `aria.cmd` assumes a local `venv\Scripts\python.exe`.
- Cloud mode requires a valid Google GenAI key and model name.
- Tavily search is wired through a runtime constant, not `config.json`.
- Reverse image search requires `serpapi_key`.
- Speech input requires microphone access plus `PyAudio`.
- Tika-based read fallback may require a Java runtime depending on the environment.
- Branch restore does not revert files on disk.

## Positioning

Aria is best understood as a terminal execution agent with a chat interface, not as a chat interface with a few tools bolted on. The modular split in this repository makes that explicit:

- the UI is operator-centric
- the LLM runtime is backend-agnostic
- the tool layer is auditable
- the integrations layer is isolated
- the system remains extensible without re-growing into a monolith

If you want a terminal AI agent that can read, plan, edit, validate, search, execute, and recover inside a real workspace with visible control flow, this repository is built for that job.
