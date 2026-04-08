<p align="center">
  <h1 align="center">openlama</h1>
  <p align="center">
    A fully local AI agent bot powered by <a href="https://ollama.com">Ollama</a>.<br>
    Chat via Telegram or terminal — tool calling, image generation, scheduled tasks, custom skills.<br>
    All running on your own hardware. Your data never leaves your machine.
  </p>
  <p align="center">
    <a href="https://pypi.org/project/openlama/"><img src="https://img.shields.io/pypi/v/openlama" alt="PyPI"></a>
    <a href="https://pypi.org/project/openlama/"><img src="https://img.shields.io/pypi/pyversions/openlama" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  </p>
  <p align="center">
    <b><a href="docs/README_ko.md">한국어</a></b>
  </p>
</p>

---

## Why openlama?

Most AI assistants send your data to cloud servers. openlama runs entirely on your local machine using Ollama, giving you a personal AI agent with full tool access and zero data leakage.

Optimized for [Gemma 4](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/) models, but works with any Ollama-compatible model.

---

## Features

- **100% Local** — No cloud APIs. All processing on your hardware.
- **Dual Channel** — Telegram bot + terminal TUI with shared conversation context.
- **20+ Built-in Tools** — Web search, code execution, file I/O, image generation, Git, Obsidian, and more.
- **Custom Skills** — Create reusable instruction sets triggered by keywords.
- **MCP Support** — Connect external tool servers via [Model Context Protocol](https://modelcontextprotocol.io).
- **Scheduled Tasks** — Cron-based recurring tasks executed by AI.
- **Memory System** — Two-tier memory: long-term (MEMORY.md) + episodic daily (auto-saved digests).
- **Multi-prompt System** — SOUL, USERS, MEMORY, SYSTEM prompts for fine-grained personality control.
- **Auto-update** — `openlama update` upgrades both openlama and Ollama.
- **Cross-platform** — macOS, Linux, Windows, **Android (Termux)**.
- **Mobile Device Control** — On Android, control your phone: camera, SMS, location, sensors, and more via Termux:API.
- **Self-healing** — `openlama doctor fix` auto-diagnoses and repairs issues.

---

## Quick Start

### 1. Install

```bash
# Recommended
uv tool install openlama

# Or with pip
pip install openlama
```

### 2. Setup

```bash
openlama setup
```

The interactive wizard will:

```
  ● Step 1/7 — Ollama
  ✓ Ollama is installed
  ✓ Ollama server running (v0.20.3)

  ● Step 2/7 — Models
  ? Select models to download:
    ✓ gemma4:e4b       9.6 GB  [recommended]
      qwen3:8b         5.2 GB  [light]
      deepseek-r1:8b   5.2 GB  [coding]
    ✓ gemma4:e2b                [installed]

  gemma4:e4b (pulling manifest)  ━━━━━━━━━━━━━━  4.2/9.6 GB  52.3 MB/s  0:01:43

  ● Step 3/7 — Channel
  ? Enter Telegram bot token (@BotFather): 1234567890:ABC...
  ✓ Connected: @your_bot_name

  ● Step 4/7 — Password
  ? Set admin password: ********

  ● Step 5/7 — Features
  ✓ ComfyUI detected: macOS Desktop App

  ● Step 6/7 — Voice Recognition (STT)
  ✓ faster-whisper is installed

  ● Step 7/7 — Obsidian Notes
  ✓ obsidian-cli is installed
  ✓ Vault connected: 13 items found

  ╭─────────────────────────────────────────────╮
  │  ✅ Setup complete!                          │
  │                                              │
  │  Start:   openlama start                     │
  │  Chat:    openlama chat                      │
  │  Doctor:  openlama doctor                    │
  ╰─────────────────────────────────────────────╯
```

### 3. Run

```bash
# Start Telegram bot in background
openlama start -d

# Open terminal chat (shares context with Telegram)
openlama chat
```

### 4. Health Check

```bash
openlama doctor
```

```
  ✓  Data directory         /home/user/.config/openlama
  ✓  Database               7 tables
  ✓  Telegram bot token     Set (12345678...nqbw)
  ✓  Python dependencies    All critical packages available
  ✓  Boot service           systemd user service registered
  ✓  Disk space             120.5 GB free
  ✓  Telegram connection    Bot @your_bot is reachable
  ✓  Ollama server          Connected (http://127.0.0.1:11434)
  ✓  Ollama version         v0.20.3 (latest)
  ✓  Ollama models          gemma4:e4b, gemma4:e2b
  !  ComfyUI                Not running (auto-start configured)

  17 passed · 1 warning(s)
```

---

## Terminal Chat (TUI)

```bash
openlama chat
```

```
──────────────────────────── openlama ─────────────────────────────
  model: gemma4:e4b | ctx: 12% (8 turns) | telegram: @your_bot
  Type / for commands, /quit to exit.

You: What's the weather in Seoul?

╭──────────────────────────── AI ─────────────────────────────────╮
│                                                                  │
│  I'll search for that.                                           │
│                                                                  │
│  Based on current data, Seoul is 18°C with partly cloudy skies.  │
│  Humidity is 45% with light winds from the northwest.            │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯
  📊 ██░░░░░░░░░░░░░░░░░░ 12.3% (2,841/32,768 tokens)  |  turns: 9
```

### Chat Commands

Type `/` to see all available commands:

```
  Chat
    /help             Show available commands
    /clear            Clear conversation context
    /status           Show session and context info
    /compress         Compress conversation context
    /session          View/extend session
    /export           Export conversation history
    /profile          Redo profile setup
    /quit             Exit chat

  Model
    /model            Show or change current model
    /models           List available models (with capabilities)
    /pull             Download a new model
    /rm               Delete a model

  Settings
    /settings         Interactive model settings
    /set <p> <v>      Change a parameter
    /think            Toggle think/reasoning mode
    /systemprompt     View/edit prompt files

  System
    /ollama           Ollama server management
    /skills           List installed skills
    /mcp              MCP server status
    /cron             View and manage scheduled tasks
```

---

## Telegram Bot

After `openlama start`, open your bot in Telegram:

1. **Login** — Send any message, enter the admin password
2. **Profile Setup** — Select language, describe yourself, set agent identity
3. **Chat** — Start chatting. The bot uses all available tools automatically.

### Telegram Features

- Inline keyboard menus for settings, model selection
- Streaming responses with real-time edits
- Image/document/audio/video/ZIP analysis
- Voice message transcription (STT via faster-whisper)
- Context bar showing token usage (Ollama actual tokens)
- Prompt file editor via inline buttons

---

## Built-in Tools (20+)

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via DuckDuckGo |
| `url_fetch` | Fetch and extract text from URLs |
| `calculator` | Evaluate math expressions |
| `code_execute` | Run Python, Node.js, or Shell code |
| `shell_command` | Execute system commands |
| `file_read` | Read files or list directories |
| `file_write` | Write or append to files |
| `git` | Git operations (status, log, diff, commit) |
| `process_manager` | List/kill processes, system status |
| `tmux` | Full tmux terminal multiplexer control |
| `image_generate` | Text-to-image via ComfyUI |
| `image_edit` | Image editing via ComfyUI |
| `memory` | Two-tier memory: long-term + daily episodic |
| `skill_creator` | Create/manage/install custom skills |
| `mcp_manager` | Install/manage MCP tool servers |
| `cron_manager` | Schedule recurring AI tasks |
| `get_datetime` | Current date and time |
| `self_update` | Check and install openlama updates |
| `whisper` | Audio/voice transcription (STT, optional) |
| `obsidian` | Obsidian vault read/write/search (optional) |
| `termux_device` | Android device control via Termux:API (Android only) |

The AI understands tool requests in any language:

> "서버 상태 확인해줘" → `shell_command`
> "search for latest AI news" → `web_search`
> "매일 10시에 뉴스 요약해줘" → `cron_manager`
> "노트 목록 보여줘" → `obsidian`
> "배터리 확인해줘" → `termux_device` (Android)

---

## Android (Termux) Setup

openlama runs on Android via [Termux](https://f-droid.org/packages/com.termux/). Two modes are supported:

### Mode 1: Remote Inference (Recommended)

Run the bot on your phone, inference on a desktop/server with a GPU.

#### Prerequisites

- [Termux](https://f-droid.org/packages/com.termux/) — Install from **F-Droid** (not Play Store)
- [Termux:API](https://f-droid.org/packages/com.termux.api/) — For device control (camera, SMS, sensors)
- [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) — For auto-start on boot (optional)
- A desktop/server running Ollama (accessible on the network)

#### Installation

```bash
# 1. Update Termux packages
pkg update && pkg upgrade -y

# 2. Install Python and Termux:API bridge
pkg install python termux-api -y

# 3. Install openlama
pip install openlama

# 4. Run setup wizard
openlama setup
#   Step 1: Select "Remote" → enter server URL (e.g., http://192.168.1.100:11434)
#   Step 2: Select model from remote server
#   Step 3: Enter Telegram bot token
#   Step 4: Set password

# 5. Start the bot
openlama start -d

# 6. (Optional) Auto-start on boot
openlama start --install-service
```

> **Note:** On the remote Ollama server, start with `OLLAMA_HOST=0.0.0.0 ollama serve` to accept network connections.

### Mode 2: On-Device Inference

Run everything on the phone (requires 8GB+ RAM).

```bash
# Install Ollama via Termux User Repository
pkg install tur-repo -y
pkg install ollama python termux-api -y

# Install openlama and run setup
pip install openlama
openlama setup    # Select "Local" → downloads a model (~3-7 GB)

openlama start -d
```

### Android Device Control

When running on Android, the `termux_device` tool gives the AI control over your phone:

| Category | Actions |
|----------|---------|
| **Phone** | call, sms_send, sms_list, call_log, contacts |
| **Camera** | camera_photo (front/rear), camera_info |
| **Audio** | mic_record, media_play, tts_speak, volume_get/set |
| **Sensors** | location, battery, sensor_list/read |
| **System** | brightness, torch, clipboard, wifi_info/scan |
| **Notifications** | notification, toast, vibrate |
| **Apps** | app_launch, app_list, share, download |

Safety rules are enforced:
- Phone calls and SMS **require explicit user confirmation**
- Location data is **never shared without consent**

### Mobile Recommended Models

| Model | Size | Notes |
|-------|------|-------|
| **`gemma4:e2b`** | **7.2 GB** | **Best for mobile** — 2.3B effective params |
| `gemma3:4b` | 3.3 GB | Good balance |
| `phi4-mini` | 2.5 GB | Lightweight |
| `gemma3:1b` | 0.8 GB | Ultra-light, minimal hardware |

### Battery Optimization

- openlama acquires a **wake lock** automatically to prevent Android from killing the process
- Disable battery optimization for Termux in your phone settings:
  - Samsung: Settings → Battery → App power management → Termux → Don't optimize
  - Xiaomi: Settings → Battery → App battery saver → Termux → No restrictions
  - Other: Settings → Apps → Termux → Battery → Unrestricted

---

## Memory System

openlama uses a two-tier memory architecture:

### Long-term Memory (MEMORY.md)
- Stores important facts, user preferences, key decisions.
- Managed via the `memory` tool (save/list/search/delete).
- Accessed by keyword search — **not loaded into system prompt** to save context for local LLMs.

### Episodic Daily Memory (memories/YYYY-MM-DD.md)
- Auto-saved conversation digests on context compression, clear, and daily flush.
- Searchable by date and keyword via the `memory` tool (list_dates/read_daily/search_daily).
- Enables the AI to recall past conversations: _"What did we talk about yesterday?"_

---

## Custom Skills

Skills are reusable instruction sets that activate on trigger keywords.

### Create via CLI

```bash
openlama skill create
```

### Create via Chat

> "Create a skill called 'code-reviewer' that triggers when I say 'review this' — it should read the file, check for bugs, and suggest fixes"

### Skill File Format

`~/.config/openlama/skills/<name>/SKILL.md`:

```markdown
---
name: code-reviewer
description: "Activated when user asks for code review"
trigger: "review, code review, check this code"
---

## Rules
1. Read the file specified by the user
2. Check for bugs, security issues, performance problems
3. Suggest improvements with code examples
```

---

## MCP Integration

Connect external tools via [Model Context Protocol](https://modelcontextprotocol.io):

```bash
# Add a server
openlama mcp add github npx -y @github/github-mcp

# With environment variables
openlama mcp add github npx -y @github/github-mcp -e GITHUB_TOKEN=ghp_xxx

# List servers
openlama mcp list

# Remove
openlama mcp remove github
```

MCP tools are automatically registered and available to the AI.

---

## Scheduled Tasks

Natural language scheduling — the AI converts to cron expressions:

> "Check disk usage every hour" → `0 */1 * * *`
> "Summarize tech news every day at 9am" → `0 9 * * *`
> "Monitor server health every 5 minutes" → `*/5 * * * *`

Each execution is a one-shot AI call with full tool access. Results are sent to your chat.

```bash
openlama cron list       # View all tasks
openlama cron delete 1   # Remove a task
```

---

## Prompt System

openlama uses a multi-file prompt architecture:

| File | Purpose | Editable |
|------|---------|----------|
| `SYSTEM.md` | Tools, rules, skills list | Auto-generated each request |
| `SOUL.md` | Agent identity and personality | Yes — `/systemprompt` |
| `USERS.md` | User profile and language | Yes — `/systemprompt` |
| `MEMORY.md` | Long-term memory entries | Via `memory` tool (not in prompt) |

All files are in `~/.config/openlama/prompts/` and can be edited via:
- **Telegram**: `/systemprompt` → select file → edit → send back
- **CLI**: `/systemprompt` → opens in `$EDITOR` (nano/vim/code)

---

## Architecture

```
~/.config/openlama/
├── openlama.db              # SQLite (settings, users, context, cron jobs)
├── openlama.pid             # Daemon PID file
├── openlama.log             # Daemon log
├── mcp.json                 # MCP server configuration
├── prompts/
│   ├── SYSTEM.md            # Auto-generated system prompt
│   ├── SOUL.md              # Agent identity
│   ├── USERS.md             # User profile
│   └── MEMORY.md            # Long-term memory (tool-accessed only)
├── memories/
│   └── YYYY-MM-DD.md        # Episodic daily memory
├── skills/
│   └── <name>/SKILL.md      # Custom skills
└── workflows/
    ├── txt2img_default.json  # ComfyUI text-to-image
    └── img2img_default.json  # ComfyUI image-to-image
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `openlama setup` | Interactive setup wizard |
| `openlama start` | Start Telegram bot (foreground) |
| `openlama start -d` | Start as background daemon |
| `openlama start --install-service` | Register OS auto-start service |
| `openlama start --uninstall-service` | Remove OS auto-start service |
| `openlama stop` | Stop daemon |
| `openlama restart` | Restart daemon |
| `openlama chat` | Terminal chat TUI |
| `openlama status` | Connection and process status |
| `openlama doctor` | Run diagnostic checks |
| `openlama doctor fix` | Auto-fix detected issues |
| `openlama update` | Update openlama + Ollama |
| `openlama config list` | View all settings |
| `openlama config get <key>` | Get a setting value |
| `openlama config set <key> <value>` | Change a setting (auto-restarts daemon) |
| `openlama config reset` | Reset all settings |
| `openlama config stt` | Show STT status |
| `openlama config stt install` | Install faster-whisper for voice recognition |
| `openlama config stt enable/disable` | Enable/disable STT |
| `openlama config obsidian` | Show Obsidian integration status |
| `openlama config obsidian install` | Install obsidian-cli |
| `openlama config obsidian vault <name>` | Set Obsidian vault |
| `openlama config obsidian disable` | Disable Obsidian integration |
| `openlama skill list` | List installed skills |
| `openlama skill create` | Create a new skill interactively |
| `openlama skill delete <name>` | Delete a skill |
| `openlama mcp list` | List MCP servers |
| `openlama mcp add <name> <cmd> [args]` | Add an MCP server |
| `openlama mcp remove <name>` | Remove an MCP server |
| `openlama tool list` | List all registered tools |
| `openlama cron list` | List scheduled tasks |
| `openlama cron delete <id>` | Delete a scheduled task |
| `openlama logs` | View daemon logs |
| `openlama --version` | Show version |

---

## Recommended Models

### Desktop / Server

| Model | Size | Best For |
|-------|------|----------|
| **`gemma4:e4b`** | **9.6 GB** | **Overall best — recommended default** |
| `gemma3:4b` | 3.3 GB | Fast responses, lower memory |
| `qwen3.5:4b` | 3.4 GB | Good multilingual support |
| `qwen3:8b` | 5.2 GB | Strong reasoning |
| `deepseek-r1:8b` | 5.2 GB | Coding tasks |
| `gemma3:1b` | 0.8 GB | Ultra-light, minimal hardware |

### Mobile (Android)

| Model | Size | Best For |
|-------|------|----------|
| **`gemma4:e2b`** | **7.2 GB** | **Best for mobile — 2.3B effective params** |
| `gemma3:4b` | 3.3 GB | Good balance for mobile |
| `phi4-mini` | 2.5 GB | Lightweight |
| `gemma3:1b` | 0.8 GB | Ultra-light, 1GB RAM devices |

---

## System Requirements

### Desktop / Server

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.11+ | 3.13+ |
| RAM | 4 GB | 8 GB+ |
| Disk | 5 GB | 20 GB+ (for models) |
| OS | macOS / Linux / Windows | macOS (Apple Silicon) |
| [Ollama](https://ollama.com) | Required | Latest version |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Optional | For image generation |

### Android (Termux)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Android | 10+ | 12+ |
| RAM | 4 GB (remote mode) | 8 GB+ (on-device) |
| Disk | 500 MB (remote) | 8 GB+ (on-device) |
| [Termux](https://f-droid.org/packages/com.termux/) | Required | From F-Droid |
| [Termux:API](https://f-droid.org/packages/com.termux.api/) | Recommended | For device control |
| [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) | Optional | For auto-start |

---

## Configuration

All settings are stored in SQLite (`~/.config/openlama/openlama.db`).

Override the data directory:

```bash
export OPENLAMA_DATA_DIR=/custom/path
```

Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `telegram_bot_token` | — | Telegram bot API token |
| `default_model` | — | Default Ollama model |
| `ollama_base` | `http://127.0.0.1:11434` | Ollama API URL |
| `comfy_enabled` | `false` | Enable ComfyUI integration |
| `comfy_base` | `http://127.0.0.1:8184` | ComfyUI API URL |
| `tool_sandbox_path` | `~/sandbox` | Sandbox for code execution |
| `obsidian_vault` | — | Obsidian vault name (enables obsidian tool) |
| `stt_enabled` | `auto` | Voice recognition: `true`/`false`/`auto` |

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest`)
5. Commit (`git commit -m 'feat: add amazing feature'`)
6. Push (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Development Setup

```bash
git clone https://github.com/sussa3007/openlama.git
cd openlama
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
openlama setup
```

---

## Roadmap

- [ ] Web UI channel
- [ ] Discord channel
- [ ] iOS Shortcuts integration
- [ ] Multi-user with separate contexts
- [ ] RAG (Retrieval-Augmented Generation) with local documents
- [ ] Voice input/output
- [ ] Plugin marketplace

---

## License

[MIT](LICENSE)

---

<p align="center">
  Built with Ollama, python-telegram-bot, Rich, and Click.<br>
  <sub>Your AI, your hardware, your data.</sub>
</p>
