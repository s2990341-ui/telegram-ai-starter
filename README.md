# Telegram AI Starter — SQLite Memory

A small, private Telegram AI assistant for Railway. Python standard library only; no pip dependencies. Bring your own Telegram bot token and Chat Completions-compatible AI provider.

## Features

- Persistent memory: last six conversation pairs per private chat.
- Required allowlist of Telegram user IDs: strangers cannot spend your AI budget.
- Per-user and total daily request limits, persisted across restarts.
- `/new` and `/delete` erase active conversation memory; `/privacy` explains data handling.
- SQLite database on a Railway persistent volume.
- Plain text responses, Unicode-safe splitting, health endpoint and graceful shutdown.
- No tokens, prompts or provider error bodies in application logs.

## Deploy on Railway

1. Put these files in a dedicated GitHub repository.
2. Create a Railway service from that repository. Dockerfile is detected; railway.json configures health checks.
3. **Attach a persistent volume at `/data` before launch.** railway.json does not create the volume.
4. Enter the five required variables below. Use a **new dedicated bot**, created through Telegram's verified @BotFather. Never reuse a token from an existing production bot.
5. Run exactly **one replica**, disable sleeping/serverless mode and avoid overlapping deployments: Telegram long polling supports one consumer per bot. No public domain is required.
6. Wait for the deployment to become healthy, open the bot from an allowlisted account, send `/start`, ask a question, then check `/delete`.

| Variable | Required | Value |
|---|---|---|
| TELEGRAM_BOT_TOKEN | Yes | Token supplied by BotFather |
| AI_API_KEY | Yes | Your provider API key |
| AI_BASE_URL | Yes | Provider HTTPS API base ending in `/v1` or equivalent, without `/chat/completions` |
| AI_MODEL | Yes | Exact model ID supporting Chat Completions and `max_tokens` |
| ALLOWED_USER_IDS | Yes | Comma-separated numeric Telegram user IDs |
| DATA_DIR | No | `/data`; must match the volume mount |
| DAILY_LIMIT | No | `30` attempted AI requests per user per UTC day |
| GLOBAL_DAILY_LIMIT | No | `300` attempted requests across all users per UTC day |
| SYSTEM_PROMPT | No | Assistant instructions |
| PORT | No | `8080`; Railway may supply its own port |

An empty allowlist or missing credentials stops startup. Group chats are ignored. A pre-existing Telegram webhook stops startup rather than modifying it automatically. No `.env` auto-loading: set environment variables using your shell or Railway UI.

## Cost and data

Railway hosting and AI calls are billed separately by their providers. Request limits are not currency caps; also configure a provider spending limit. Failed AI calls consume a request slot. A request denied by the global limit also consumes a per-user slot.

The AI provider receives the current message and retained conversation context. SQLite retains up to six pairs until `/delete`; backups may retain earlier copies. Usage counters contain chat IDs and are cleaned on the next AI request after the UTC date changes. Configure volume backups and retention according to your needs. This is a general-purpose starter, not a medical records system.

## Operational limitations

One process handles messages sequentially; this is a starter for small private bots, not a high-throughput public SaaS. Updates are checkpointed before processing (at-most-once): a crash can lose a response, but will not automatically repeat a paid AI call. Telegram delivery failures are not replayed. Health checks indicate recent polling, not AI-provider availability. No file, voice, payments or admin dashboard support.

## Local checks

Python 3.12 or newer:

```sh
python -m unittest -v
```

To run locally, export the required variables and set `DATA_DIR=./data`, then `python bot.py`. Keep secrets outside source control.

## Marketplace publication

See `PUBLISH_RU.md`. This archive is source code, **not yet a published Railway template**. No template ID or earnings are claimed.
