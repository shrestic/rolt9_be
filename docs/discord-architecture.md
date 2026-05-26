# Discord Architecture — End-to-end Workflow

> This document explains the **entire workflow** of the project: from a user clicking a button on the dashboard, from a user typing a slash command in Discord, all the way through to the bot/BE calling the Discord API and replying back. After reading this you should understand exactly how the code runs.

---

## 1. Bird's-eye view

The project runs as **one Python process**: a single FastAPI app whose lifespan starts the Discord bot as a background task. The HTTP server and the discord.py gateway share the same event loop, the same memory, and the same in-process objects (bot cache, config, services).

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Single Python process                       │
│                          (uvicorn app.main:app)                      │
│                                                                      │
│   ┌──────────────────────────────┐   ┌────────────────────────────┐  │
│   │  FastAPI HTTP server         │   │  discord.py bot            │  │
│   │  ──────────────────────      │   │  ──────────────────        │  │
│   │  - Dashboard REST routes     │   │  - WebSocket gateway       │  │
│   │  - OAuth login               │   │  - Slash commands          │  │
│   │  - /me, /guilds, /moderation │   │  - on_message listener     │  │
│   │  - Health check              │   │  - In-memory guild cache   │  │
│   └──────────────┬───────────────┘   └─────────────┬──────────────┘  │
│                  │                                 │                 │
│                  │  share via app.state.bot        │                 │
│                  └──────────────┬──────────────────┘                 │
│                                 ▼                                    │
│                  ┌────────────────────────────┐                      │
│                  │  BotDiscordClient          │                      │
│                  │  (wraps discord.py for     │                      │
│                  │   service / endpoint use)  │                      │
│                  └────────────────────────────┘                      │
│                                                                      │
│                  ┌────────────────────────────┐                      │
│                  │  RestDiscordOAuthClient    │                      │
│                  │  (httpx, OAuth flow only)  │                      │
│                  └────────────────────────────┘                      │
│                                                                      │
└──────────────────────────┬───────────────────────┬───────────────────┘
                           │                       │
                           ▼                       ▼
                  ┌─────────────────┐    ┌─────────────────┐
                  │  PostgreSQL     │    │  Discord API    │
                  │  (users,        │    │  + Gateway      │
                  │   guilds,       │    │  (HTTP + WS)    │
                  │   mod_cases,    │    └─────────────────┘
                  │   settings)     │
                  └─────────────────┘
```

- Entry point: [main.py](../main.py) → [app/main.py](../app/main.py)
- `app/main.py`'s lifespan calls `build_bot()`, runs `bot.start(...)` as an `asyncio` task, waits for `bot.wait_until_ready()`, then assigns `app.state.bot`.
- On shutdown the lifespan calls `bot.close()`.

Why one process? See [section 2](#2-why-one-process).

---

## 2. Why one process?

We used to have two: `bot_main.py` ran the bot as its own Python process, and `main.py` ran FastAPI as another. They only communicated through PostgreSQL. That model:

- Required a second container in `docker-compose` and a second deploy pipeline.
- Forced every dashboard read to make a round trip to Discord's REST API (because FastAPI had no bot instance and therefore no gateway cache).
- Duplicated config — both processes loaded the full `.env` but each used a different subset.
- Made cache invalidation hard — admins editing settings in the dashboard had to wait 45 s for the bot's `GuildConfigCache` TTL to expire.
- Surfaced as a stale `is_active` flag on the dashboard when the bot was down but the row still said it was in the guild.

After the merge:

- One container, one deploy.
- `GET /guilds/{id}/overview` goes from ~600 ms (three REST calls) to <10 ms (three cache reads).
- Settings updates can call `app.state.bot.config_cache.invalidate(...)` directly to bust the cache instantly.
- `bot.is_ready()` is a live signal — no DB flag drift.

The tradeoff: restarting the HTTP server also restarts the bot. For our scale (<10 k guilds, no sharding) that's a non-issue. If we ever needed to scale beyond a single gateway shard, we'd split it back out.

---

## 3. Why does `app/discord_io/` exist?

Before the refactor, Discord I/O was scattered everywhere:

- Cogs called `await guild.ban(target)` directly.
- Endpoints instantiated `httpx.AsyncClient()` and hit `discord.com/api/...`.
- Every call site invented its own error handling.

The pain:

- **Hard to read** — service code mixed Discord SDK calls with DB logic; you couldn't tell them apart.
- **Hard to test** — you had to mock `discord.Guild.ban` or httpx in a dozen places.
- **Hard to change the SDK** — a discord.py 3.x release would touch dozens of files.

**The fix**: a single wrapper layer at `app/discord_io/` that consolidates all Discord I/O. Services / cogs / endpoints depend only on two interfaces (`DiscordClient`, `DiscordOAuthClient`) — they never touch `discord.*` or `httpx`.

---

## 4. Directory layout

```
app/
├── discord_io/                         ★ I/O LAYER — wraps every Discord interaction
│   ├── client.py                       Protocols: DiscordModeration + DiscordReader + DiscordMessaging
│   │                                              + DiscordClient (union) + DiscordOAuthClient
│   ├── types.py                        Dataclasses: Embed, GuildInfo, ChannelInfo, ...
│   ├── errors.py                       4 exceptions: DiscordError/NotFound/Forbidden/RateLimited
│   └── clients/
│       ├── bot.py                      BotDiscordClient — implements DiscordClient via discord.py
│       └── rest.py                     RestDiscordOAuthClient — implements DiscordOAuthClient via httpx
│
├── services/                           ★ BUSINESS LAYER — orchestrates the flow
│   ├── moderation/
│   │   ├── __init__.py                 Re-exports Actor, ModerationService, ...
│   │   ├── actor.py                    Actor (user_id + username) — collapsed from discord.Member
│   │   ├── service.py                  ModerationService — single entry point for cogs / endpoints
│   │   ├── embeds.py                   build_case_embed(case) -> Embed
│   │   ├── delivery.py                 deliver_case — post to mod-log + DM target
│   │   └── escalation.py               next_escalation rule for /warn
│   ├── oauth_session.py                Refresh-near-expiry policy for user access tokens
│   ├── permission_service.py           Checks whether a user has MANAGE_GUILD
│   └── custom_command_service.py       Template rendering + cooldown logic
│
├── api/v1/endpoints/                   ★ REST LAYER (FastAPI)
│   ├── auth.py                         OAuth login + callback + logout
│   ├── me.py                           /me + /me/guilds
│   ├── guilds.py                       /{guild_id}/overview
│   └── moderation.py                   settings + cases (CRUD)
│
├── bot/                                ★ DISCORD BOT (discord.py)
│   ├── client.py                       Rolt9Bot, event handlers, BotDiscordClient construction
│   ├── events.py                       handle_guild_join/remove/ready (take GuildInfo)
│   ├── cache/guild_config_cache.py     In-memory cache for GuildConfig
│   └── cogs/
│       ├── moderation.py               /ban /kick /mute /unmute /unban /warn /warnings /case
│       └── custom_commands.py          Intercepts on_message → matches custom commands
│
├── repositories/                       ★ DB CRUD
│   ├── user.py, guild.py, guild_settings.py, mod_case.py, custom_command.py
│   └── base.py
│
├── models/                             SQLAlchemy models
├── schemas/                            Pydantic DTOs (request/response)
├── dependencies/                       FastAPI Depends factories
│   ├── auth.py                         get_current_user (session cookie → User)
│   ├── services.py                     DI factories for repos + services + clients
│   └── guild.py                        require_managed_guild
├── core/                               config + crypto + JWT
├── db/                                 SQLAlchemy session
├── exceptions/                         HTTP error classes + handler
├── middlewares/                        CORS + logging + clientid
└── main.py                             FastAPI app + lifespan that starts the bot
```

---

## 5. Layering & principles

```
┌──────────────────────────────────────────────────────────┐
│  LAYER 1 — Entry points                                  │
│                                                          │
│  • app/bot/cogs/*.py             (slash commands)        │
│  • app/api/v1/endpoints/*.py     (HTTP routes)           │
│  • app/bot/events.py             (guild join/remove)     │
│                                                          │
│  Responsibility: parse input, call service, format output│
│  Forbidden: calling `guild.ban()` directly,              │
│             calling httpx against discord.com            │
└──────────────────────────────────────────────────────────┘
                          │ calls
                          ▼
┌──────────────────────────────────────────────────────────┐
│  LAYER 2 — Services (business orchestration)             │
│                                                          │
│  • ModerationService                                     │
│  • OAuthSessionService                                   │
│  • PermissionService                                     │
│                                                          │
│  Responsibility: business flow, DB reads/writes,         │
│                  building Embeds                         │
│  Forbidden: import discord, httpx against discord.com    │
└──────────────────────────────────────────────────────────┘
                          │ calls
                          ▼
┌──────────────────────────────────────────────────────────┐
│  LAYER 3 — Discord clients (pure I/O)                    │
│                                                          │
│  • Three small Protocols for actions / reads / messaging │
│    - DiscordModeration  (ban/kick/mute/unmute/revoke)    │
│    - DiscordReader      (get_guild/list_*/get_user)      │
│    - DiscordMessaging   (post_to_channel/notify_user_…)  │
│  • DiscordClient = the union of all three                │
│    └─ BotDiscordClient   (uses discord.py)               │
│  • DiscordOAuthClient Protocol (separate)                │
│    └─ RestDiscordOAuthClient (uses httpx)                │
│                                                          │
│  Each consumer depends on the narrowest protocol it      │
│  needs (e.g. deliver_case takes DiscordMessaging).       │
│                                                          │
│  Responsibility: I/O with Discord, error normalization   │
└──────────────────────────────────────────────────────────┘
```

### The 5 immovable rules

| # | Rule | File(s) allowed to break it |
|---|------|------------------------------|
| 1 | `import discord` for SDK actions | `app/discord_io/clients/bot.py` |
| 2 | `httpx` against `discord.com` | `app/discord_io/clients/rest.py` (OAuth only) |
| 3 | Method names express business intent (`ban_member`, not `create_guild_ban`) | — |
| 4 | Errors normalize to the 4 exceptions in `app/discord_io/errors.py` | Adapters raise SDK exceptions internally and convert |
| 5 | `guild_id`/`user_id`/`channel_id` are always Discord snowflakes (`int`) | Repos use internal UUIDs but never expose them |

> Small exception to rule 1: cogs (`app/bot/cogs/*.py`) and `bot/client.py` are allowed to `from discord.ext import commands` and to type-hint `discord.Interaction`/`discord.Member`. That's **framework integration** (subclassing Cog, receiving objects the framework hands them). They still are NOT allowed to call `interaction.guild.ban()` directly — they must go through `self.discord_io.ban_member(...)`.

---

## 6. Detailed end-to-end workflows

### 6.1 Startup

```
1. uvicorn imports app.main → app/main.py executes
2. app/main.py imports app.dependencies.services. At this point:
      _http = httpx.AsyncClient(timeout=10.0)
      _oauth_client = RestDiscordOAuthClient(http=_http)
      _oauth_session = OAuthSessionService(oauth=_oauth_client)
      _perm_svc = PermissionService(oauth=_oauth_client)
   are created as module-level singletons.

3. uvicorn enters the FastAPI lifespan (in app/main.py):
      bot = build_bot()                                 # Rolt9Bot + cogs + BotDiscordClient
      bot_task = asyncio.create_task(bot.start(TOKEN))  # gateway connect in the background
      await bot.wait_until_ready()                      # block startup until bot is ready
      app.state.bot = bot

4. discord.py emits READY → on_ready event handler in bot/client.py runs:
      handle_ready([_guild_info_from(g) for g in bot.guilds], session)
      → handle_guild_join for each connected guild → upsert + create_defaults

5. Uvicorn starts accepting HTTP requests.
```

### 6.2 OAuth login flow

```
[Browser]                           [FastAPI]                           [Discord]
   │                                    │                                  │
   │  Clicks "Login with Discord"       │                                  │
   ├───────────────────────────────────►│                                  │
   │  GET /api/v1/auth/discord/login    │                                  │
   │                                    │  endpoint auth.py::discord_login │
   │                                    │  - generate state token (CSRF)   │
   │                                    │  - set state cookie              │
   │                                    │  - build authorize URL           │
   │                                    │                                  │
   │  302 Redirect to Discord           │                                  │
   │◄───────────────────────────────────┤                                  │
   │                                    │                                  │
   │  GET discord.com/oauth2/authorize?...                                 │
   ├──────────────────────────────────────────────────────────────────────►│
   │                                    │                                  │
   │  User authorizes (first time) or auto-redirects (consent given)       │
   │◄──────────────────────────────────────────────────────────────────────┤
   │  302 Redirect to /auth/discord/callback?code=...&state=...            │
   │                                    │                                  │
   │  GET /api/v1/auth/discord/callback?code=...&state=...                 │
   ├───────────────────────────────────►│                                  │
   │                                    │  endpoint auth.py::discord_callback
   │                                    │  DI: oauth(DiscordOAuthClient),
   │                                    │      users(UserRepository)
   │                                    │  - assert state cookie == query state (CSRF)
   │                                    │  - oauth.exchange_oauth_code(code)
   │                                    │     │ tokens                     │
   │                                    │     ├──────────────────────────►│
   │                                    │     │ POST /oauth2/token        │
   │                                    │     │◄──────────────────────────┤
   │                                    │     │ {access, refresh, ...}    │
   │                                    │  - oauth.get_user_me(access_token)
   │                                    │     │ user info                 │
   │                                    │     ├──────────────────────────►│
   │                                    │     │ GET /users/@me            │
   │                                    │     │◄──────────────────────────┤
   │                                    │  - users.upsert(...)             │
   │                                    │     → DB row (tokens encrypted)  │
   │                                    │  - create_session_token(user.id)│
   │                                    │  - set rolt9_session cookie     │
   │                                    │  - delete oauth_state cookie    │
   │                                    │                                  │
   │  302 Redirect /dashboard           │                                  │
   │◄───────────────────────────────────┤                                  │
   │                                    │                                  │
```

OAuth still goes through `httpx` because the bot has no way to exchange user bearer tokens — that's specifically what `RestDiscordOAuthClient` is for.

Code path:
1. [api/v1/endpoints/auth.py:discord_login()](../app/api/v1/endpoints/auth.py) — generate state, redirect
2. [api/v1/endpoints/auth.py:discord_callback()](../app/api/v1/endpoints/auth.py) — exchange + upsert
3. [discord/clients/rest.py:exchange_oauth_code()](../app/discord_io/clients/rest.py) — POST `/oauth2/token`
4. [discord/clients/rest.py:get_user_me()](../app/discord_io/clients/rest.py) — GET `/users/@me`

### 6.3 Dashboard "Choose a server"

After login, the user lands on the dashboard → FE calls `GET /api/v1/me/guilds`.

```
[FE]                            [FastAPI]                       [Discord]    [DB]
 │                                  │                              │           │
 │  GET /api/v1/me/guilds           │                              │           │
 ├─────────────────────────────────►│                              │           │
 │                                  │ endpoint me.py::my_guilds    │           │
 │                                  │ DI: current=User, perms,     │           │
 │                                  │     oauth_session, users,    │           │
 │                                  │     guilds                   │           │
 │                                  │                              │           │
 │                                  │ 1. oauth_session.get_valid_access_token  │
 │                                  │    OAuthSessionService:                   │
 │                                  │    - decrypt user.access_token_enc       │
 │                                  │    - if expires_at - now > 60s: return   │
 │                                  │    - else: oauth.refresh_oauth_token →   │
 │                                  │             upsert encrypted tokens      │
 │                                  │                              │           │
 │                                  │ 2. perms.list_my_managed_guilds(token)   │
 │                                  │    PermissionService:                    │
 │                                  │    - cache hit (60s TTL)? → return       │
 │                                  │    - cache miss:                         │
 │                                  │      oauth.list_guilds_of_user(token)    │
 │                                  │      ┌──────────────────────►│           │
 │                                  │      │ GET /users/@me/guilds │           │
 │                                  │      │◄──────────────────────┤           │
 │                                  │      filter MANAGE_GUILD /                │
 │                                  │      ADMINISTRATOR bit                   │
 │                                  │                              │           │
 │                                  │ 3. guilds.get_active_by_discord_ids(...) │
 │                                  │    ───────────────────────────────────►│
 │                                  │    SELECT * WHERE discord_id IN (...)   │
 │                                  │                                ◄────────│
 │                                  │    set of guild_ids the bot is in       │
 │                                  │                              │           │
 │                                  │ 4. format → [GuildSummary(..., bot_present=...)]
 │  200 OK                          │                              │           │
 │◄─────────────────────────────────┤                              │           │
```

Code:
- [api/v1/endpoints/me.py:my_guilds()](../app/api/v1/endpoints/me.py)
- [services/oauth_session.py](../app/services/oauth_session.py)
- [services/permission_service.py](../app/services/permission_service.py)
- [discord/clients/rest.py:list_guilds_of_user()](../app/discord_io/clients/rest.py)

### 6.4 Dashboard "Server overview" — the big speedup

User picks a server → FE calls `GET /api/v1/guilds/{guild_id}/overview`.

```
[FE] ──► [FastAPI endpoint guilds.py::guild_overview]
            │
            │ DI: current(User), perms, oauth_session, users, discord(DiscordClient)
            │     ↑ `get_discord_io(request)` reads app.state.bot.discord_client
            │       — i.e. the live BotDiscordClient sharing the bot's gateway cache.
            │
            │ 1. Auth + permission check (same as 6.3):
            │    token = oauth_session.get_valid_access_token(...)
            │    perms.user_can_manage(token, guild_id)? → 403 if not
            │
            │ 2. Fetch from Discord via BotDiscordClient — three cache reads:
            │    guild    = discord_io.get_guild(gid)        ← bot.get_guild(gid) (RAM)
            │    channels = discord_io.list_channels(gid)    ← guild.channels (RAM)
            │    roles    = discord_io.list_roles(gid)       ← guild.roles (RAM)
            │
            │ 3. Format → GuildOverview { name, icon_url, member_count, channels[], roles[] }
            │
            ▼
        200 OK   (<10 ms total — no Discord REST calls)
```

Before the merge this endpoint made three HTTP round trips to Discord (~600 ms). After the merge those become RAM reads on the bot's gateway cache. The only Discord HTTP call left in this endpoint is the OAuth permission check.

### 6.5 Slash command `/ban` (still inside the same process)

A user types `/ban @member spam` in Discord.

```
[Discord gateway]  ──►  [discord.py dispatcher]  ──►  [ModerationCog.ban()]
                                                       │
                                                       │ interaction = discord.Interaction
                                                       │ member       = discord.Member
                                                       │
                                                       │ 1. _run_action helper wraps the body:
                                                       │      await interaction.response.defer(ephemeral=True)
                                                       │      try:
                                                       │          async with AsyncSessionLocal() as session:
                                                       │              service = _build_service(session, self.discord_io)
                                                       │              message = await do(service)
                                                       │      except (ValueError, LookupError, DiscordError) as exc:
                                                       │          await interaction.followup.send(friendly_msg(exc), ephemeral=True)
                                                       │          return
                                                       │      await interaction.followup.send(message, ephemeral=True)
                                                       │
                                                       │ 2. The cog's `do(service)` closure:
                                                       │      target    = Actor.from_member(member)
                                                       │      moderator = Actor.from_member(interaction.user)
                                                       │      case = await service.ban(guild_id=..., target=..., moderator=..., reason=...)
                                                       │      return f"Banned {member} — case #{case.case_number}"
                                                       │
                                                       │ 3. ModerationService.ban() inside the service:
                                                       │    ┌─────────────────────────────────┐
                                                       │    │   a. _load_guild_and_settings   │
                                                       │    │      → SELECT guild, settings   │
                                                       │    │      (raises LookupError if     │
                                                       │    │       guild not registered)     │
                                                       │    │   b. self.discord_io.ban_member │
                                                       │    │      → BotDiscordClient         │
                                                       │    │      → guild.ban(Object(id=..)) │
                                                       │    │      → Discord PUT /bans/...    │
                                                       │    │   c. self._record("ban", ...)   │
                                                       │    │      → INSERT mod_case          │
                                                       │    │   d. deliver_case(...)          │
                                                       │    │      → post embed to mod-log    │
                                                       │    │      → DM target (if enabled)   │
                                                       │    │   return ModCase                │
                                                       │    └─────────────────────────────────┘
                                                       ▼
                  (Moderator sees ephemeral reply via followup)
                  (Mod-log channel shows the case embed)
                  (Target receives a DM)
```

Read closely:
- [bot/cogs/moderation.py:ban()](../app/bot/cogs/moderation.py) — entry
- [services/moderation/service.py:ban()](../app/services/moderation/service.py) — orchestration
- [discord/clients/bot.py:ban_member()](../app/discord_io/clients/bot.py) — SDK call
- [services/moderation/delivery.py:deliver_case()](../app/services/moderation/delivery.py) — post + DM
- [services/moderation/embeds.py:build_case_embed()](../app/services/moderation/embeds.py) — build the Embed

### 6.6 Slash command `/warn` (with auto-escalation)

`/warn` is special — beyond recording a warn case, when the warn count hits a configured threshold the bot **automatically** applies an action (mute or ban).

The whole warn-and-maybe-escalate sequence runs inside a process-local `asyncio.Lock` keyed by `(guild_id, target_user_id)`. Without it, two moderators warning the same user simultaneously could both read the count before either committed, and both miss (or both fire) the escalation threshold. The lock keeps the count → check-rule → apply sequence atomic per target. If we ever shard into multiple processes, swap to a PostgreSQL advisory lock.

If the escalation rule says `mute` with a duration longer than Discord's 28-day max, the service clamps the duration silently so the auto-mute still succeeds.

Example settings:
```json
{
  "warn_escalation": [
    {"threshold": 3, "action": "mute", "duration_seconds": 3600},
    {"threshold": 5, "action": "ban"}
  ]
}
```

```
3rd warn on the user:
  → service.warn() records case (#10, action=warn, source=manual)
  → deliver_case(#10)
  → count = cases.active_warn_count(...) = 3
  → next_escalation(3, rules) = {"action": "mute", "duration_seconds": 3600}
  → discord_io.mute_member_until(...)
  → record case #11 (action=mute, source=escalation, moderator=AutoMod#0)
  → deliver_case(#11)
  → return (#10, #11)

4th warn (between 3 and 5):
  → next_escalation(4, rules) = None
  → return (#case_warn, None)

5th warn:
  → next_escalation(5, rules) = {"action": "ban"}
  → discord_io.ban_member(...)
  → record case (action=ban, source=escalation)
  → deliver_case
```

Cog replies with:
```
"Warned @bad — case #10"                                       (no escalation)
"Warned @bad — case #10 · auto-mute applied (case #11)"        (escalated)
```

### 6.7 Dashboard "Deactivate case" — single code path for both sides

A moderator clicks "Deactivate" on a ban case in the dashboard → FE calls `DELETE /api/v1/guilds/{guild_id}/cases/{case_number}`.

```
[FE] ──► [FastAPI endpoint moderation.py::deactivate_case]
            │
            │ DI: guild (require_managed_guild), cases (ModCaseRepository),
            │     moderation (ModerationService with BotDiscordClient)
            │
            │ 1. Look up the case by (guild.id, case_number). 404 if not found.
            │
            │ 2. Call moderation.deactivate_case(guild_id=guild.discord_id, case=c)
            │    ┌──────────────────────────────────────────────────┐
            │    │ ModerationService.deactivate_case():             │
            │    │   if case.action == "ban":                       │
            │    │       discord_io.revoke_ban(guild_id, target_id) │
            │    │       └─► BotDiscordClient.revoke_ban            │
            │    │           └─► guild.unban(Object(id=...))        │
            │    │               discord.NotFound → swallow         │
            │    │               discord.Forbidden → DiscordForbidden│
            │    │   elif case.action == "mute":                    │
            │    │       discord_io.unmute_member(guild_id, ...)    │
            │    │       └─► BotDiscordClient.unmute_member         │
            │    │           └─► member.timeout(None, ...)          │
            │    │               (member missing → swallow)         │
            │    │   # warn / kick / unmute / unban → record-only,  │
            │    │   # nothing to undo on Discord                   │
            │    │   self.cases.deactivate(case)                    │
            │    │       └─► UPDATE mod_case SET active=false       │
            │    └──────────────────────────────────────────────────┘
            │
            │ 3. Catch DiscordError:
            │    raise BadRequestError(error_code="REVOKE_FAILED")
            │
            │ 4. Return _case_out(c) (200 OK)
            │
            ▼
       200 OK {case_number, action, active: false, ...}
```

**Key point**: the bot cog `/unban` AND the FastAPI endpoint `DELETE /cases/{n}` both go through `ModerationService`, which delegates to **the same BotDiscordClient instance**. There is exactly one code path; no duplication.

Note that `/unban` (the cog command) also runs an `is_banned` pre-check on the service side. If the target isn't currently banned, the service raises `LookupError` and the cog replies "User is not currently banned" instead of recording a misleading "unban" case.

### 6.8 Custom command `!rules` (prefix command)

The admin defines a custom command in the dashboard:
```
{ trigger: "rules", response_type: "text", response_text: "Hi {user}, read the rules!" }
```

A user types `!rules` in a channel.

```
Discord gateway → MESSAGE_CREATE → discord.py fires on_message
  │
  ▼
CustomCommandsCog.on_message(message):
  - message.author.bot? → skip
  - message.guild is None? (DM) → skip
  - config = await self.cache.get(guild.id)
    └─► GuildConfigCache: cache miss → load from DB → cache it
  - handle_message(message, self.discord, config, self._cooldowns)
    │
    ▼
handle_message:
  1. config.enabled? Yes
  2. Prefix match? "!rules".startswith("!") = True
  3. trigger = "rules"
  4. cmd = config.commands.find(trigger == "rules") → found
  5. is_allowed(roles, channel, ...)? True
  6. is_on_cooldown(...)? False; set cooldown[key] = now
  7. context = {user: "Alice", server: "S", member_count: "100", ...}
  8. cmd.response_type == "text" → discord_client.post_to_channel(
       channel.id, content=render_template(cmd.response_text, context)
     )
     └─► BotDiscordClient.post_to_channel
         └─► channel.send(content="Hi Alice, read the rules!")
```

---

## 7. Error model

### 7.1 Discord I/O errors

Every `DiscordClient` / `DiscordOAuthClient` method raises only one of 4 exceptions:

| Exception | When | HTTP/SDK source | Caller handling |
|-----------|------|-----------------|-----------------|
| `DiscordNotFound` | Target doesn't exist | 404 / `discord.NotFound` | Usually ignore (idempotent) or 404 to the FE |
| `DiscordForbidden` | Bot/user lacks permission | 403 / `discord.Forbidden` | 400 REVOKE_FAILED to the FE, or log + swallow |
| `DiscordRateLimited` | Discord 429 | 429 | No auto-retry yet; bubble up |
| `DiscordError` | Anything else | 5xx / `discord.HTTPException` | Bubble up |

Service code only catches `DiscordError` (the base class) — or nothing at all. It never writes `try: ... except discord.NotFound`.

Several adapter methods are intentionally **idempotent** — they swallow `DiscordNotFound` because the goal state is already met:

| Method | Why idempotent |
|---|---|
| `revoke_ban` | If the user isn't banned, "unbanned" is the goal anyway. |
| `kick_member` | If the user already left the guild, they're effectively kicked. |
| `mute_member_until` / `unmute_member` | Members not in the guild can't be muted, so a missing-member is treated as success. |

### 7.2 Service errors

Beyond Discord I/O, the service layer can also raise plain built-in exceptions for non-Discord issues — pick whichever fits best so cogs and endpoints can keep their `try/except` lists short:

| Exception | When |
|---|---|
| `LookupError` | Guild not registered in our DB; user not banned (so `/unban` can't proceed). |
| `ValueError` | Mute duration > 28 days (Discord's hard cap). |
| `SessionExpiredError` | OAuth refresh token rejected — only the user can recover by logging in again. Mapped to HTTP 401 with `error_code: SESSION_EXPIRED` via a global exception handler. |

### 7.3 Example caller patterns

Endpoint translating `DiscordError` to HTTP 400:

```python
try:
    await moderation.deactivate_case(guild_id=..., case=c)
except DiscordError as exc:  # catches NotFound / Forbidden / RateLimited too
    raise BadRequestError(detail="...", error_code="REVOKE_FAILED") from exc
```

Best-effort swallow inside delivery (never re-raise; the main action already succeeded):

```python
try:
    await discord_io.post_to_channel(channel_id, embed=embed)
except DiscordError:
    log.warning(...)
```

Cog `_run_action` helper catches all three categories at once so every slash command stays terse — see section 11 for the pattern.

---

## 8. DI mapping — what each factory injects

Everything is defined in `app/dependencies/services.py` and the bot owns its own DiscordClient.

| Dependency | Returns | Singleton? | Used by |
|------------|---------|------------|---------|
| `get_user_repository` | `UserRepository(db)` | No (per-request) | Endpoints needing user data |
| `get_guild_repository` | `GuildRepository(db)` | No | Moderation, guilds endpoints |
| `get_guild_settings_repository` | `GuildSettingsRepository(db)` | No | Moderation endpoints |
| `get_mod_case_repository` | `ModCaseRepository(db)` | No | Moderation endpoints |
| `get_custom_command_repository` | `CustomCommandRepository(db)` | No | Commands endpoints |
| `get_discord_io(request)` | `app.state.bot.discord_io` (`BotDiscordClient`) | **Yes** (lives on the bot) | Guilds, moderation endpoints |
| `get_oauth_client` | `_oauth_client: RestDiscordOAuthClient` | **Yes** | Auth endpoint |
| `get_oauth_session_service` | `_oauth_session: OAuthSessionService` | **Yes** | Me, guilds endpoints |
| `get_permission_service` | `_perm_svc: PermissionService` | **Yes** | Me, guilds endpoints, dependency `guild.py` |
| `get_moderation_service` | `ModerationService(db, BotDiscordClient, ...)` | No | Moderation endpoints |

On the bot side, the cogs construct `ModerationService` inline (because they need a DB session per command):

```python
class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io     # the same BotDiscordClient FastAPI uses

    async def ban(self, interaction, member, reason=None):
        async with AsyncSessionLocal() as session:
            service = ModerationService(
                session=session, discord_io=self.discord_io,
                guilds=GuildRepository(session),
                settings=GuildSettingsRepository(session),
                cases=ModCaseRepository(session),
            )
            case = await service.ban(...)
```

---

## 9. Database

The 3 main tables involved in moderation:

```
guilds                      guild_settings               mod_cases
─────────────────────       ────────────────────         ────────────────────────────
id (UUID, PK)               id (UUID, PK)                id (UUID, PK)
discord_id (int, unique)    guild_id (FK → guilds.id)    guild_id (FK → guilds.id)
name                        moderation (JSONB)           case_number (int, unique/guild)
icon_url                    welcome (JSONB)              action (ban/kick/mute/...)
is_active                   automod (JSONB)              source (manual/escalation)
                            logging (JSONB)              target_user_id (bigint)
                            commands (JSONB)             target_username
                                                         moderator_user_id (bigint)
users                                                    moderator_username
─────────────────────       custom_commands              reason
id (UUID, PK)               ────────────────────         duration_seconds
discord_id (bigint, unique) id (UUID, PK)                expires_at
username                    guild_id (FK)                created_at
avatar_url                  trigger                      active (bool)
access_token_enc            response_type
refresh_token_enc           response_text
token_expires_at            embed (JSONB)
                            allowed_role_ids (JSONB[])
                            allowed_channel_ids (JSONB[])
                            cooldown_seconds
                            enabled
```

ID convention:
- `guilds.id`, `mod_cases.id`, `users.id` = internal UUIDs (used only inside the DB)
- `guilds.discord_id`, `users.discord_id`, `mod_cases.target_user_id`, ... = Discord snowflakes (int64)
- Services and DiscordClient always work with snowflakes; the repo converts to UUID when needed.

---

## 10. Test architecture

### Unit tests (`tests/unit/`)

Test one class/function from `app/services/` or `app/discord_io/` using `tests/fakes/discord.py::FakeDiscordClient` instead of calling Discord. The `db_session` fixture from `conftest.py` provides an in-memory SQLite.

```python
# tests/unit/test_moderation_service.py
discord_io = FakeDiscordClient()
service = ModerationService(db_session, discord_io, repos...)
await service.ban(guild_id=55, target=Actor(7, "x"), ...)
assert (55, 7) in discord_io.bans              # service called ban_member
assert len(discord_io.posted_messages) == 1     # posted to mod-log
```

### Integration tests (`tests/integration/`)

Spawn a `TestClient` against the FastAPI app (full DI stack). Two boundaries are mocked differently because they use different transports:

- **OAuth side** (`/oauth2/token`, `/users/@me`, `/users/@me/guilds`) still goes through `httpx` → mocked with `respx`.
- **Bot side** (revoke_ban, get_guild, list_channels, list_roles, ...) now goes through `BotDiscordClient` → `respx` can't intercept that. We inject a `FakeDiscordClient` via FastAPI's `dependency_overrides`.

`conftest.py` does this automatically:

```python
# autouse fixture — every test gets a fresh FakeDiscordClient bound to get_discord_io
@pytest.fixture(autouse=True)
def _default_fake_discord_override(request):
    ...
    fake = FakeDiscordClient()
    app.dependency_overrides[get_discord_io] = lambda: fake
    yield
    ...

# opt-in fixture — tests that need to seed or inspect state ask for the same instance
@pytest.fixture
def fake_discord():
    ...
    fake = FakeDiscordClient()
    app.dependency_overrides[get_discord_io] = lambda: fake
    yield fake
    ...
```

Example test that needs to assert on the fake:

```python
async def test_deactivate_ban_revokes_discord_ban(seed, db_session, fake_discord):
    client, g = await seed()
    c = await ModCaseRepository(db_session).create_case(action="ban", ...)
    fake_discord.bans.add((GID, 7))             # seed: the user is banned
    _mock_owned()                                # respx mock for OAuth permission check
    r = client.delete(f"/api/v1/guilds/{GID}/cases/{c.case_number}")
    assert r.status_code == 200
    assert (GID, 7) not in fake_discord.bans    # service revoked the ban via BotDiscordClient
```

### Fakes (`tests/fakes/`)

- `FakeDiscordClient` — implements `DiscordClient`, in-memory.
- `FakeOAuthClient` — implements `DiscordOAuthClient`, in-memory.
- Both record every call so tests can assert what happened.

The lifespan is NOT triggered in most tests (`TestClient` is used without a `with` block). The autouse override means `get_discord_io` returns the fake even though `app.state.bot` was never set.

---

## 11. When you need to do something

### The slash-command cog pattern (`_run_action` helper)

Every moderation slash command in `app/bot/cogs/moderation.py` follows the same shape, wrapped by one helper:

```python
async def _run_action(interaction, discord_io, action):
    await interaction.response.defer(ephemeral=True)    # ack within 3 s
    try:
        async with AsyncSessionLocal() as session:
            service = _build_service(session, discord_io)
            message = await action(service)
    except ValueError as exc:        # bad input  (e.g. mute > 28 days)
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        return
    except LookupError as exc:       # missing thing (guild not registered, user not banned)
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        return
    except DiscordError as exc:      # Discord-side failure (permissions, rate limit)
        await interaction.followup.send(
            f"❌ Discord rejected the action ({type(exc).__name__}). ...",
            ephemeral=True,
        )
        return
    await interaction.followup.send(message, ephemeral=True)
```

Each command then becomes a thin closure:

```python
@app_commands.command(name="ban", ...)
async def ban(self, interaction, member, reason=None):
    async def do(service):
        case = await service.ban(guild_id=..., target=..., moderator=..., reason=...)
        return f"Banned {member} — case #{case.case_number}"
    await _run_action(interaction, self.discord_io, do)
```

Three things the helper buys you for free:

1. `defer()` first — slash interactions must be ack'd within 3 seconds. Anything beyond that (DB roundtrip + Discord call + DM) goes through `followup.send`, which has a 15-minute window.
2. Catches the three expected failure categories and replies with a friendly message — no more raw "Interaction failed" toast on the moderator's screen.
3. Centralizes the "open DB session, build service" boilerplate.

When you add a new slash command, prefer this pattern. Reach for the raw `defer / try / followup` form only if you need behavior the helper can't express.

### Add a new moderation action (e.g. `/note`)

1. Add the method `note_member(...)` to **one** of the small Protocols in `app/discord_io/client.py`. Pick the narrowest fit (most actions live on `DiscordModeration`).
2. Implement it in `BotDiscordClient`. Update `FakeDiscordClient` to match.
3. Add `note(...)` to `ModerationService` (orchestrate the DB write + delivery).
4. Add a `/note` slash command in `ModerationCog`, using the `_run_action` pattern above.
5. (Optional) Add a REST endpoint if the dashboard needs to trigger it.
6. Write tests using `FakeDiscordClient`.

### Add a new read query (e.g. "list cases for a user")

If the data lives in the DB:

1. Add a method to `ModCaseRepository` (the SQL).
2. Add a wrapper method to `ModerationService` (the public API). Mirror the existing `count_active_warns` / `get_case` shape — take Discord snowflakes, return DTOs.
3. Use the service method from both the cog and the endpoint — don't reach past the service into the repo from a cog or endpoint. (Repos are private to the service layer.)

### Add a read endpoint (e.g. list members)

1. Add `list_members(guild_id)` to `DiscordClient`.
2. Implement it in `BotDiscordClient` (`guild.members`) and `FakeDiscordClient`.
3. Add an endpoint in `api/v1/endpoints/guilds.py` and inject `DiscordClient` via `get_discord_io`.
4. Test with a seeded `fake_discord` fixture.

### Change how you talk to Discord (e.g. add rate-limit retries)

- Only modify `BotDiscordClient` (for bot actions) or `RestDiscordOAuthClient` (for OAuth).
- Don't touch `ModerationService`, cogs, or endpoints.

### Migrate to discord.py v3 / nextcord

- Only rewrite `BotDiscordClient`.
- The `DiscordClient` Protocol stays the same. Services / cogs / endpoints are untouched.

### Run without a bot for local API-only development

- Leave `DISCORD_BOT_TOKEN` blank in `.env`.
- The lifespan logs a warning and skips bot startup.
- Endpoints that depend on `get_discord_io` will fail with `RuntimeError` unless overridden — convenient for backend-only HTTP work that doesn't touch Discord.

---

## 12. One-page summary

```
                ┌─────────────────────────────────────────┐
                │   Single Python process (uvicorn)        │
                │                                          │
                │   FastAPI HTTP      ◄── shares ──►   Bot │
                │   (endpoints/)                  (cogs/) │
                │           │                       │      │
                │           └──── BotDiscordClient ─┘      │
                │           │                              │
                │           └── RestDiscordOAuthClient     │
                │               (OAuth only, httpx)        │
                │                                          │
                └──────────────────┬───────────────────────┘
                                   ▼
                           Discord API + Gateway
```

- **One process; the bot is a background task inside FastAPI's lifespan.**
- **Services and endpoints never see `discord.py` or `httpx`.**
- **Cogs and endpoints never write to the DB directly** — they go through a service or a repo.
- **`BotDiscordClient` is the single in-memory wrapper** that both cogs (via `self.discord_io`) and endpoints (via `app.state.bot.discord_io`) use.
- **`RestDiscordOAuthClient` is the only piece left that uses `httpx`**, and only for OAuth.
- **Errors normalize to 4 exceptions. Method names follow business intent.**

If you've read this far, you understand the architecture. Anything still unclear — ask 😄
