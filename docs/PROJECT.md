# Azeroth Soulforge — Durable Project Specification

**Document version:** 3.0

**Status:** runnable alpha

**Last reviewed:** 2026-08-29

This document is the durable source of truth for the project. Code, contracts,
operations, and milestone claims must agree with it.

## 1. Vision and success criteria

Azeroth Soulforge enables a private solo/LAN AzerothCore realm that begins with
one immutable `w0rld` prompt. The prompt becomes canon for people, dialogue,
relationships, rumors, and narrative plans. The owner enters a fresh staged-
Vanilla realm with four automatically selected dungeon companions, lives in it
at their own pace, and pauses it when they leave.

The project uses *soul* as approachable product language for that continuity. It
does not assert consciousness, sentience, inner experience, or literal life.

The first complete release succeeds when:

- A pinned AzerothCore Playerbots fork and module build reproducibly.
- A role-balanced dungeon party is generated from available Playerbots, and
  additional encountered bots can be promoted to deep-memory companions.
- Humans can interact with souls through in-game chat and a local dashboard.
- Meaningful events become attributable memories that survive restarts.
- Slow or unavailable inference never stalls the world update loop or gameplay.
- Realm phases advance sequentially only after a verified database backup.
- An eight-hour, 40-companion soak run shows no cross-soul memory leakage,
  duplicate deliveries, runaway bot conversations, or LLM-related world stalls.

## 2. Scope and non-goals

In scope: Linux source deployment for localhost or trusted LAN; AzerothCore
3.3.5a with the required Playerbots fork; a prompted narrative world; deep-
memory companions; shared population memory; in-game dialogue; an authenticated
LAN dashboard; local Ollama plus owner-configured OpenAI, Anthropic, Gemini, and
OpenAI-compatible inference; normalized usage accounting; and manual Vanilla-
to-Wrath progression.

Not in v1: a public internet realm, direct LLM gameplay control, generated game
quests/rewards/content, claims of consciousness, voice chat, a custom client, or distribution
of game assets, extracted data, and model weights.

## 3. Architecture and ownership

```text
WoW client
    |
AzerothCore worldserver + Playerbots
    | approved events       ^ scheduled chat delivery
mod-soulbridge worker queue/outbox client
    | authenticated local HTTP
Soul Service (Python HTTP service)
    |-- durable inbox and reply outbox
    |-- prompted-world canon, narrative director, identity and memory
    |-- provider routing, usage ledger and authenticated admin API
    |-- SQLite in WAL mode
    |
Ollama or owner-configured paid text APIs; local embeddings

trusted LAN browser --HTTPS--> nginx gateway --> React assets/admin API
                                                  |
                                      internal allowlisted control agent
                                                  |
                                  Docker socket + AzerothCore config only
```

- **AzerothCore and Playerbots** own combat, movement, questing, inventory,
  gearing, talents, groups, raids, and every gameplay action.
- **mod-ah-bot** optionally supplies auction-house inventory and purchasing
  through a dedicated, owner-selected character. Both buyer and seller start
  disabled.
- **mod-soulbridge** observes approved events and transports them. It contains
  no personality or memory policy.
- **Soul Service** owns immutable world canon, world time, narrative plans,
  profiles, memory, relationships, provider routing, usage, prompts, dashboard
  behavior, and the durable outbox.
- **React dashboard** manages non-secret bot, soul, model, and server settings
  through same-origin administration APIs.
- **Control Agent** is an internal-only, Docker-privileged allowlist for service
  state, game-server lifecycle, Playerbot roster queries, and selected configs.
- **Provider adapters** perform generation behind a replaceable server-side
  interface and are never called from the game process. Embeddings stay local.

The C++ module must enqueue quickly and return. Dedicated worker code performs
HTTP. Replies return through a world-thread-safe scheduler. No network,
database, model, filesystem, or other blocking operation may occur
synchronously on the world update thread.

The repository's `make up` and `make down` commands control the complete app.
Docker Compose builds and runs MySQL, Ollama, the Soul Service, database import,
client-data initialization, authserver, and worldserver. Setup clones exact
upstream revisions into ignored runtime storage and syncs Soulbridge into the
build context. Preflight refuses placeholders or unexpected source revisions;
a startup failure tears down only this Compose project.
Initial bot/player settings from `.env` seed generated AzerothCore configuration
once. Later dashboard changes edit that persistent configuration and therefore
survive container recreation and whole-app shutdown.
Module configuration follows AzerothCore's generated `etc/modules/` layout;
startup copies distribution templates to active configuration files before
applying the initial Playerbot values.
Startup applies the pinned Auction House Bot world schema through a one-time
migration ledger. It adopts an already complete schema but refuses to replace
an incomplete schema automatically because the upstream base SQL is
destructive.
The first `make up` runs an idempotent Playerbots prewarm before authentication
is exposed. A maintenance-only worldserver creates the configured population,
waits for every bot to log in, flushes generated state, records the prepared
population in private runtime state, and stops. Normal world starts keep random
bots offline until a human connects, then admit them in bounded background
batches after a short grace period. `make bots` exposes the same prewarm as an
explicit stopped-server operation.
The core retains its complete level-80 stat tables because lowering
`MaxPlayerLevel` below the Death Knight start level makes AzerothCore abort.
The active progression brackets gate content, while the Playerbots-specific
maximum keeps generated companions at level 19 for the initial phase.
The worldserver receives the pinned `mod-playerbots/data/sql` tree as a
read-only bind mount because Playerbots initializes and updates its separate
database at worldserver startup; AzerothCore's minimized runtime image does not
otherwise contain module source SQL.
Authserver and worldserver readiness checks connect to their internal TCP
listeners, so whole-stack startup does not report success while either process
is still initializing or caught in a restart loop.

## 4. Event and reply flow

Capture chat involving a soul plus guild/group changes, quest completions,
deaths, resurrections, trades, notable loot, dungeon completion, boss kills,
and phase unlocks. Exclude routine combat, movement ticks, damage events, and
ambient random-bot activity. Events use `contracts/events.schema.json` and are
idempotent by `event_id`.

1. Soulbridge submits a compact event from its worker queue.
2. The service validates, authenticates, deduplicates, and persists it.
3. Policy decides whether it deserves a reply or memory extraction.
4. Inference priority is whisper, party/raid, guild, say, then proactive chat.
5. Prompts contain canonical identity, current scene, bounded recent turns,
   relationship context, and a small retrieved-memory set.
6. The reply enters a durable outbox with an expiry.
7. Soulbridge polls, validates, schedules delivery, and acknowledges it.

Delivery is at-least-once until acknowledgement; consumers deduplicate by reply
ID. Expired replies are not spoken. During outages, Playerbots continues and
soul chat is temporarily silent.

Generated responses carry a trace ID, origin, and hop count. A generated bot
message may cause at most one further bot reply. Duplicate suppression,
per-bot cooldowns, channel budgets, and a guild-wide budget prevent cascades.
Human messages begin a new trace.

## 5. Soul and memory model

The identity key is `(realm_id, character_guid)`. Names and other character
attributes are mutable display data.

Each soul has a seeded canonical profile; recent context; episodic memories with
participants, provenance, emotional tone, importance, and confidence;
per-character relationship dimensions; summaries; promises; goals; shared guild
history; and an edit/delete audit trail.

Every forged companion also has a materialized
`/data/profiles/<realm>/<CharacterName>/SKILL.md`. The human-facing path uses the
current unique character name, while the frontmatter and database retain the
immutable AzerothCore GUID as the identity key. The service owns the canonical
profile and memory-ledger sections; the owner edits a separate character-skill
section for history, mannerisms, loyalties, fears, goals, and boundaries. That
guidance is included in dialogue prompts. SQLite remains authoritative for
transactional memory indexing, and the document is refreshed after profile or
memory changes.

Canonical facts cannot be rewritten by generated output. Relationship changes
are bounded per event. Each companion retains at most 60 recent raw chat
messages. Exchanges enter a temporary 12-item world buffer; after eight, the
director distills only durable promises, relationships, discoveries, decisions,
and unresolved threads into shared memory. Successful compaction deletes the
raw buffer, and trivial interactions may produce no durable memory at all. Raw
event payloads retain at most seven days or 2,000 completed events; expired
outbox rows are collected. The distilled non-canonical ledger retains the 400
highest-importance recent facts while founding and narrative events are
protected.

Retrieval combines SQLite FTS keyword ranking with cosine similarity over local
embeddings, then filters by soul, participants, phase, recency, importance, and
visibility. At 40-soul scale, vectors can be scored in process. Deleting a
memory removes it from retrieval and deletes its embedding. Export/import uses
the versioned soul schema and excludes secrets.

## 6. Local inference

- Default dialogue model: `qwen3.5:4b` Q4_K_M.
- CPU fallback: `qwen3:1.7b` when host benchmarks miss the latency target.
- Optional later upgrade: a suitable 8B model after benchmarking.
- Embeddings: `embeddinggemma:300m-qat-q4_0`.
- One generation worker on CPU/small-GPU hosts; embeddings are lower priority.
- Direct-message target: p95 response time at or below 15 seconds during normal
  play on the deployment host.

Prompts are strictly in-world. Souls do not mention prompts, LLMs, databases,
servers, modern life, or implementation details. Changing a model never changes
soul identity.

## 7. Progression and data safety

Target the Playerbots `Playerbot` core fork and `mod-playerbots` at pinned
revisions. Accept `mod-progression-system` only after a disposable-database
build and runtime compatibility test.

Phases follow the supported Vanilla-to-TBC-to-Wrath sequence and unlock manually.
Before each unlock: run preflight checks, quiesce writes, back up all AzerothCore
and Soul databases, validate checksums, restore-test a disposable database,
apply exactly the next phase, and run content/Playerbots smoke tests.

Never downgrade in place. Restore the complete pre-phase snapshot after failure.
If the progression module is incompatible, first maintain a minimal patch. If
semantics remain unsafe, implement a separate phase-gating module behind the
same dashboard manifest rather than weakening Playerbots.

## 8. Dashboard and security

The React administration UI is exposed only through an HTTPS gateway on the
configured trusted-LAN address. `make up` creates a self-signed certificate for
that address. Authentication uses a distinct admin password, 12-hour Secure,
HttpOnly, SameSite=Strict sessions, CSRF tokens on mutations, two layers of
login rate limiting, request size limits, security headers, and a LAN firewall
allowlist. MySQL, Ollama, SOAP, Soul Service, and the control agent are not
published to the LAN.

The control agent has Docker-socket authority and is therefore treated as a
host-administration boundary. It accepts only an internal bearer secret and an
explicit operation allowlist; it exposes no arbitrary command, SQL, filesystem,
or container API. The browser never receives any infrastructure secret.

The dashboard's Home page is the everyday control surface: prompted-world state,
human presence, world playtime, Enter/Leave controls, service state, companion
status, AI kill switch, active director/dialogue routes, normalized token usage,
and estimated spend. World, Companions, AI Studio, Client Addons, and Advanced pages
separate story continuity from infrequent administration. API credentials are
encrypted at rest and never returned to the browser. Progression controls remain
absent until backup verification and restore testing are automated.

The repository ships Soulforge Commander as a required ConsolePortLK 1.5.0-rc2
plugin. Setup downloads exact checksum-pinned ConsolePortLK and legacy Windows
WoWmapperX archives into ignored runtime storage, and the authenticated dashboard
assembles them with Soulforge Commander as one client pack. The plugin registers
a managed ConsolePort ring for seven Playerbots orders plus a
controller-navigable Companions panel. The ring takes ConsolePort's default
utility-ring bar chord without changing movement bindings. It has
no network or AI authority and every command remains user initiated. General
macros remain a troubleshooting fallback.

Bridge requests require a shared-secret signature, timestamp window,
nonce/replay protection, size limits, and strict schema validation. MariaDB,
Ollama, and administration ports are never exposed directly to the internet.

Public operator documentation is a dependency-free static site in `site/`,
deployed from `main` through the least-privilege GitHub Pages workflow. The
public site contains no runtime state, game assets, secrets, or dashboard
authority and is operationally separate from the private LAN control plane.

## 9. Public APIs

`contracts/openapi.yaml` is authoritative:

- `POST /v1/events` accepts an authenticated idempotent event and returns `202`.
- `GET /v1/outbox` returns unexpired pending replies for a realm consumer.
- `POST /v1/outbox/{reply_id}/ack` acknowledges delivery.
- Soul export/import follows `contracts/soul-export.schema.json`.
- Trusted-LAN administration follows `contracts/admin-openapi.yaml`.

Breaking formats require a new version. Additive optional fields may enter v1
only when existing consumers remain safe.

## 10. Roadmap

| Milestone | Status | Exit condition |
| --- | --- | --- |
| Public repository and contracts | Complete | Public CI-green scaffold |
| Upstream compatibility spike | Complete | Pinned Docker build passes |
| Soulbridge transport | Alpha | Async HMAC event/outbox transport builds |
| Soul Service core | Alpha | SQLite inbox/outbox and bridge APIs implemented |
| Memory and relationships | Partial | Recent per-soul dialogue persists; richer model pending |
| Ollama dialogue | Alpha | `qwen3.5:4b` local chat adapter implemented |
| Dashboard | Alpha | Authenticated HTTPS React control plane and safe admin workflows |
| Prompted fresh world | Alpha | Immutable seed, canon, dungeon group and narrative plans persist |
| Provider routing and usage | Alpha | Local/paid adapters, kill switch and usage ledger pass tests |
| Soulforge Commander | Alpha | Pinned ConsolePortLK/WoWmapperX pack, managed bar binding, and addon checks pass; physical-client smoke pending |
| Public setup documentation | Complete | Beginner guide deploys through GitHub Pages |
| Progression integration | Alpha | Initial level-19 phase configured; later unlock workflow pending |
| Guild acceptance | Not started | Eight-hour, 40-soul soak criteria pass |

## 11. Verification

Automated tests cover schema validation, idempotency, realm/GUID isolation,
acknowledgement, expiry, trace limits, memory deletion, and outage behavior.
Integration tests must prove inference failure does not affect the world loop.

Compatibility claims record commands, exact revisions, OS, compiler/database
versions, test baseline, date, and outcome here.

### Compatibility evidence

On 2026-08-26, Ubuntu 22.04 host/Docker Engine built the official Ubuntu 24.04
container targets with Clang 18 and C++20. Command:
`docker compose --env-file .env.example build ac-worldserver ac-authserver
ac-db-import ac-client-data-init soul-service`. Revisions were core
`9fb906bb7296212ff42fc95ff73a92aaf8554f0d`, Playerbots
`2f7d9f774987d0157c6a0d0cc08c40bec3db3945`, and progression
`84a25e6df8497d83432e61aa38557a92c156e77d`. CMake discovered all three
modules and produced worldserver, authserver, dbimport, client-data, and Soul
Service images successfully. A live database/client login smoke test remains
pending operator secrets.

On 2026-08-27, the same Docker/Clang toolchain built and linked worldserver
with official `mod-ah-bot` revision
`a680cc1c98290713e9b3d3289544af78e5186dc1` alongside the pinned Playerbots,
progression, and Soulbridge modules. The module configuration and all three
world-database SQL inputs were present in the resulting build context.

Also on 2026-08-26, Docker Engine 29.4 built the React-enabled Soul Service and
Docker CLI 29.6.1 control-agent images. `./scripts/verify.sh` passed Python admin
session/CSRF/profile/SKILL.md tests, control-agent safety tests, the React
19.2.8/Vite 8.2.2 production build, Compose rendering, shell validation, and the
C++ queue test. An isolated container test ran nginx TLS termination, logged in
through the admin API, forged `Thorn`, edited its character guidance, verified
`/data/profiles/azeroth-soulforge/Thorn/SKILL.md`, and confirmed that `/v1`
bridge routes return 404 through the LAN gateway. An in-app visual browser
inspection was unavailable in the implementation environment; production asset
compilation and HTTP/TLS behavior were verified directly.

The repository also seeds `examples/profiles/Thorn/SKILL.md` and provides
`scripts/validate-skill-inference.py`. The validator creates Thorn under the
immutable internal identity `(skill-validation, 1842)`, loads the owner-editable
skill section, submits a signed whisper through the production event endpoint,
waits on the durable outbox, and requires the selected local Ollama model to
return the profile-only phrase `silver acorn`. This heavyweight integration
check is explicit rather than part of normal CI because it requires installed
model weights. On 2026-08-26 the check passed against the pinned Ollama 0.33.0
runtime and locally installed `qwen3.5:4b`. Soul Service accepted the event and
the durable reply began: `A silver acorn, tucked safely under the old stone.`
Because that keepsake exists only in Thorn's owner-editable skill section, this
demonstrates that the production inference worker supplied `SKILL.md` context to
the local model.

## 12. Architecture decision log

Entries are append-only. Supersede rather than rewriting an earlier decision.

### 2026-08-25 — Separate social intelligence from gameplay

**Decision:** Playerbots owns gameplay; the LLM is limited to social behavior
and suggestions expressed in dialogue.

**Reason:** Deterministic game AI is fast and safe; inference is slow, fallible,
and best suited to language.

**Consequence:** v1 exposes no LLM-to-Playerbots command interface.

### 2026-08-25 — Use an out-of-process Soul Service

**Decision:** AzerothCore communicates asynchronously with a local service over
versioned HTTP contracts.

**Reason:** Model and memory work must not destabilize world updates.

**Consequence:** The bridge needs queues, acknowledgement, deduplication,
authentication, and graceful outage behavior.

### 2026-08-25 — Use SQLite for the first 40 souls

**Decision:** Store soul state separately in SQLite WAL mode.

**Reason:** The single-host workload does not justify another database service.

**Consequence:** Writes are serialized and migrations require versioning.

### 2026-08-25 — Manual sequential realm progression

**Decision:** Only the owner unlocks the next phase after a validated backup.

**Reason:** Applied progression SQL can be unsafe to reverse piecemeal.

**Consequence:** v1 has no calendar or boss-triggered automatic unlocks.

### 2026-08-26 — Use one Docker Compose application

**Decision:** Build and operate AzerothCore, Playerbots, progression, Soul
Service, Ollama, and databases as one named Compose project.

**Reason:** It removes host compiler/database prerequisites and makes `make up`
and `make down` truthful whole-app controls.

**Consequence:** The initial build/download is large; persistent named volumes
survive normal shutdown, and unrelated containers are untouched.

### 2026-08-26 — Default dialogue to Qwen3.5 4B

**Decision:** Use Ollama model tag `qwen3.5:4b` as the default local dialogue
model.

**Reason:** It fits this 30 GiB host comfortably while providing a stronger
small-model baseline than the earlier Qwen3 choice.

**Consequence:** Model identity remains separate from soul identity and may be
changed after latency/quality benchmarking.

### 2026-08-26 — Use an authenticated LAN React control plane

**Decision:** Serve a Vite-built React client through an HTTPS gateway with
password sessions, CSRF defense, rate limiting, and a LAN firewall allowlist.

**Reason:** The realm owner needs to manage bots, souls, models, and routine
server settings without an SSH session while keeping credentials off the client.

**Consequence:** Browsers must accept or locally trust the generated certificate;
the dashboard is for a trusted LAN and is not approved for internet exposure.

### 2026-08-26 — Isolate Docker authority behind an allowlist

**Decision:** Put Docker-socket and AzerothCore configuration access in an
internal control-agent container with no host port and no arbitrary operations.

**Reason:** Server lifecycle and persistent settings require host authority, but
placing that authority directly in a LAN-facing web service would increase risk.

**Consequence:** The agent remains a sensitive host-administration boundary and
must stay small, authenticated, internal-only, and explicitly allowlisted.

### 2026-08-26 — Keep models replaceable at runtime

**Decision:** Let authenticated administrators install any valid Ollama model
tag and select among installed models without changing soul identity.

**Reason:** Host capabilities vary, and larger models may improve dialogue on
machines with more memory or acceleration.

**Consequence:** The operator owns model licensing, disk, memory, and latency
tradeoffs; `qwen3.5:4b` remains only the portable default.

### 2026-08-26 — Publish dependency-free operator documentation

**Decision:** Keep the public setup website as static HTML, CSS, and minimal
JavaScript in `site/`, deployed by the official GitHub Pages artifact actions.

**Reason:** New operators need a readable guide before cloning the repository,
and a dependency-free site avoids a second package toolchain and supply chain.

**Consequence:** Operator-facing behavior changes must update the README, the
Markdown getting-started guide, and the Pages site together.

### 2026-08-26 — Keep realm type administrator-selectable

**Decision:** Expose Normal, PvP, RP, and RP-PvP as a validated dashboard
setting, updating both AzerothCore's gameplay configuration and the realm-list
icon before restarting the worldserver.

**Reason:** Realm owners should be able to choose their ruleset without editing
configuration files or issuing database commands on the host.

**Consequence:** Free-for-all PvP and arbitrary numeric realm types remain
outside the control-agent allowlist.

### 2026-08-27 — Expose bounded gameplay rates

**Decision:** Let administrators adjust grouped experience, reputation, item
loot, money, honor, and profession skill-gain multipliers from the dashboard.

**Reason:** These are common private-realm preferences and should not require
host access or error-prone manual edits across several related configuration
keys.

**Consequence:** Values are restricted to 0.1×–10×, profession gains use whole
numbers from 1×–10×, and applying any rate restarts only the worldserver.
Progression brackets and Playerbot level caps remain independent safety gates.

### 2026-08-27 — Allow large staged random-bot populations

**Decision:** Permit 0–2,000 random bots through the validated dashboard and
default new installations to 500 random bots.

**Reason:** Capable hosts can create a busier world, and random population bots
do not need Soulforge profiles or LLM inference.

**Consequence:** The 2,000-bot value is an administrative ceiling rather than a
hardware guarantee. Operators must increase populations in stages and monitor
worldserver CPU and latency.

### 2026-08-27 — Keep Auction House Bot opt-in

**Decision:** Build the official `mod-ah-bot`, but require an unused, logged-out
character selected in the dashboard and leave both buying and selling disabled
until the owner enables them.

**Reason:** A populated auction house improves a private realm, while explicit
character assignment prevents the module from silently taking over a played
character.

**Consequence:** Startup applies the pinned module schema through a guarded
migration. Transmog, solo-scaling, and account-wide-convenience modules remain
out of scope.

### 2026-08-27 — Provide a controller-sized party commander for human tanks

**Decision:** Bundle an optional WoW 3.3.5a addon with five Playerbots actions:
follow, hold, attack, rebuff, and flee. It selects party or raid automatically;
mouse modifiers can address one named companion or healer-role bots, while controller users
cycle among those three scopes with one explicit binding.

**Reason:** A human tank needs immediate, deliberate group control without a
large controller binding surface or granting Soulforge's social layer gameplay
authority.

**Consequence:** The addon is installed only in a user's legal local WoW client,
never changes bindings automatically, and remains limited to user-initiated
chat commands supported by Playerbots.

### 2026-08-27 — Supersede the client addon with General Macros

**Decision:** Remove Party Commander and document five controller-ready General
Macros instead: follow, hold, attack, rebuff, and flee. Each macro chooses the
current party or raid, with Ctrl for one named companion and Shift for healer-role bots.

**Reason:** The owner requested a limited controller surface without installing
or maintaining a client addon.

**Consequence:** WoW keeps macros in client account data, so the realm cannot
force them onto characters. Creating them as General Macros makes them
available to every character on that WoW account; players still choose the
action-bar and controller bindings.

### 2026-08-27 — Expose a new-character boost level

**Decision:** Add a validated 1–80 dashboard setting that writes both
`StartPlayerLevel` and `StartHeroicPlayerLevel` for characters created after it
is applied.

**Reason:** The owner wants fresh alts to reach endgame quest chains quickly
while retaining those quest chains, gearing, attunements, and raid preparation
as gameplay.

**Consequence:** The setting restarts the worldserver, never edits existing
characters, and does not grant gear, skills, professions, reputations, flight
paths, or progression unlocks. `55` is documented as the practical raid-prep
quest starting point; `1` remains the default.

### 2026-08-29 — Make one immutable prompt the root of a fresh world

**Decision:** A new installation begins by converting one owner-written
`w0rld` prompt into immutable structured canon, founding tensions, narrative
plans, and four role-balanced companion profiles.

**Reason:** The owner should feel that they are entering one coherent world,
not managing unrelated bots and model settings.

**Consequence:** Generated memories and plans may extend canon but never rewrite
it. Alpha-era world migration is not a supported requirement; normal restarts
of a forged world remain durable.

### 2026-08-29 — Advance narrative time only during human play

**Decision:** Aggregate non-bot presence controls world playtime. The realm
auto-stops after the configurable grace period following the last human logout.

**Reason:** Companions and plans must not progress ahead while the owner is away.

**Consequence:** Wall-clock downtime triggers no catch-up. The control agent
exposes only an allowlisted aggregate presence query.

### 2026-08-29 — Compact conversation before it becomes world memory

**Decision:** Raw companion chat is bounded and temporary. A periodic director
pass promotes only durable facts into the shared world ledger.

**Reason:** Greetings, command chatter, and repetition should neither inflate
storage and prompts nor accidentally harden into world history.

**Consequence:** Personal context keeps 60 messages, the pending world buffer
keeps 12 exchanges, and compaction begins at eight. Failed or disabled inference
cannot create unbounded growth because the temporary buffer still evicts old
entries. Raw events retain at most seven days or 2,000 completed records, and
the distilled non-canonical ledger is capped at 400 facts.

### 2026-08-29 — Route director and dialogue through server-side provider profiles

**Decision:** Support Ollama, OpenAI, Anthropic, Gemini, and generic OpenAI-
compatible providers with separate director/dialogue routes, encrypted API
keys, normalized usage, an optional paid cap, and a global kill switch.

**Reason:** World creation may benefit from a stronger paid model while frequent
dialogue remains affordable and private on local hardware.

**Consequence:** Paid profiles are explicit opt-in data egress. Credentials are
write-only to the browser, provider bills are authoritative, and reaching a cap
falls back to local Ollama when available.

### 2026-08-30 — Bootstrap paid AI without an unused local-model download

**Decision:** A fresh install with `SOULFORGE_OPENAI_API_KEY` skips the default
Ollama model pull and imports an encrypted OpenAI profile once. A trailing
`/v1` is normalized, and GPT-5/o-series requests omit unsupported temperature.

**Reason:** Owners who already chose paid inference should not download unused
weights, and current reasoning models reject some legacy sampling controls.

**Consequence:** AI Studio remains authoritative after first boot; startup never
overwrites an existing provider profile or route.

### 2026-08-29 — Supersede macros with a hold-to-open radial commander

**Decision:** Ship Soulforge Commander as a downloadable 3.3.5a addon. A mapped
button opens a cursor-centered radial wheel; mouse direction selects an order
and button release executes it.

**Reason:** A visual command wheel is faster and more natural than typing chat
commands or maintaining a bank of action-bar macros.

**Consequence:** The addon still emits only user-initiated, supported Playerbots
chat commands. It has no HTTP, credential, inference, or autonomous gameplay
authority. The prior macro approach remains only a fallback.

### 2026-08-30 — Synchronize the installed addon from the active world

**Decision:** Keep Soulforge Commander's package character-agnostic. The addon
requests `.soulforge roster` after login; Soulbridge resolves the active world's
ordered bindings asynchronously and returns machine-readable system messages.
The addon saves enabled state and local additions in SavedVariables and exposes
them in Companion Setup.

**Reason:** Each fresh world has its own people. Operators should be able to
forge a party, download the addon, and play without editing Lua or inheriting
another world's example character names.

**Consequence:** The client addon remains external-network-free and
credential-free. It is installed once, server roster changes synchronize without
a new download, and players can configure who Assemble invites from inside WoW.

### 2026-08-31 — Keep random-bot login batches responsive

**Decision:** Seed `AiPlayerbot.ReactDelay` at 250 ms,
`AiPlayerbot.RandomBotUpdateInterval` at 30 seconds, and
`AiPlayerbot.RandomBotsPerInterval` at 25 while retaining the independently
configurable total random-bot population.

**Reason:** Live comparison with the prior installation showed that the pinned
Playerbots stack remained responsive to a real client's world login with these
values, while the fresh defaults evaluated each bot 2.5 times as often and used
60-bot asynchronous batches that starved the realm-to-character-selection
handoff during a fresh 700-bot startup.

**Consequence:** Large populations take longer to reach their target after a
worldserver restart and individual bot reactions may be up to 150 ms later,
but authentication, character selection, and world responsiveness retain
priority.

### 2026-08-31 — Prewarm bots before exposing player login

**Decision:** Make the first `make up` prepare durable Playerbot state in a
maintenance-only world, expose the workflow separately as `make bots`, and keep
random bots offline until a human connects during normal operation.

**Reason:** First-login bot generation performs substantial character-database
work. Running it before authserver starts prevents that work from competing with
the owner's realm-to-character-selection handshake.

**Consequence:** Initial setup takes longer and reports bot progress explicitly.
The prewarm is idempotent for an unchanged or smaller configured population,
normal shutdown retains its private completion marker and database state, and a
larger population causes the preparation phase to run again.

### 2026-08-31 — Size MySQL for a populated private realm

**Decision:** Run MySQL with a 4 GiB configurable InnoDB buffer pool, flush redo
logs once per second, and disable per-transaction binary-log synchronization.

**Reason:** Live diagnosis of a fresh 700-bot realm found MySQL still using its
128 MiB default after 16.7 million uncached InnoDB page reads and 932,163
fsyncs. The resulting database churn stretched paced bot startup and left 932
character writes queued during shutdown.

**Consequence:** Bot state and world tables remain cached on suitably sized
hosts, while `SOULFORGE_DB_BUFFER_POOL_SIZE` supports smaller deployments. A
machine or container crash can lose up to roughly one second of recent database
work; normal shutdown still drains all committed work.

### 2026-08-31 — Make the Commander package directly discoverable

**Decision:** Load `Bindings.xml` from Soulforge Commander's TOC and document
the exact extracted client path in the dashboard and setup guide.

**Reason:** WoW 3.3.5a ignores ZIP files and addons nested below an extra folder,
and a binding file omitted from the TOC cannot register the command-wheel key.

**Consequence:** The addon appears when extracted to
`Interface/AddOns/SoulforgeCommander`, and its hold-to-open binding is available
without editing client files.

### 2026-08-31 — Expose safe AI usage telemetry

**Decision:** Emit one structured `ai_call` line after every director or
dialogue inference and return a 24-hour hourly usage series to AI Studio. Logs
and the plot separate input and output tokens; logs also include provider,
model, status, latency, cached input, reasoning, and total tokens.

**Reason:** Operators need to correlate world activity with paid inference,
understand usage over time instead of reading only a cumulative number, and
diagnose slow or unexpectedly expensive routes from ordinary container logs.

**Consequence:** Prompts, generated text, character conversations, and provider
credentials remain excluded from operational logs and chart data. Monthly
totals and estimated spend remain available alongside the rolling plot.

### 2026-08-31 — Keep companion replies in the initiating chat

**Decision:** Capture human-authored companion mentions from say, party, raid,
guild, and public channel chat in addition to direct whispers, preserve the
originating destination in the durable outbox, and deliver generated dialogue
back through that same destination.

**Reason:** A companion answering a party line by whisper breaks the shared
conversation, while ignoring say and General prevents the player from naturally
initiating public role-play.

**Consequence:** Shared channels require an explicit companion-name mention,
only human-authored messages enter the inference path, public-channel replies
require the bot to be present in that channel, and generated output cannot
trigger another event. Chat capture remains a bounded enqueue on the world
thread; all HTTP and inference work stays on workers.

### 2026-08-31 — Split deep companions from ambient realm chatter

**Decision:** Keep forged companions on the high-quality dialogue route and add
a separate local ambient route using `qwen3:1.7b`, a 96-token ceiling, a five
percent default reply chance, and a 30-second global cooldown. Ambient prompts
receive the current zone and public channel but no personal-memory transcript.

**Reason:** A convincing classic realm needs occasional zone-aware chatter from
ordinary population bots, but applying the companion model and deep context to
every public line would waste tokens and make a 1,000-bot realm noisy.

**Consequence:** At most one eligible same-faction random bot is considered for
each human say or public-channel line. Most events are dismissed before
inference, generated messages cannot re-enter capture, and ambient bots do not
accumulate deep memories. AI Studio controls the ambient route, chance, and
cooldown and can preview each companion's bounded assembled prompt.

### 2026-08-31 — Deliver model dialogue as literal character chat

**Decision:** Require companion, ambient, and banter routes to return only the
first-person words the character would type into the WoW chat box. Normalize
speaker labels, wrapping quotes, and leading emotes before delivery, and suppress
outputs that still begin as third-person narration or stage direction.

**Reason:** General role-play instructions can cause a model to narrate a
character, label its answer, or describe an action instead of speaking as the
character. Those formats look artificial when injected into WoW chat.

**Consequence:** In-game replies read as ordinary player messages. A malformed
narrative response is silently discarded instead of being shown, and item or
spell references such as `[Rupture]` remain ordinary chat text.

### 2026-08-31 — Run ambient chatter at the measured traffic ceiling

**Decision:** Raise fresh-install ambient defaults from a five percent chance
and 30-second cooldown to the allowed maximum of a 25 percent chance and
five-second global cooldown. Keep `qwen3:1.7b`, thinking disabled, and the
96-token output ceiling.

**Reason:** Production-style CPU benchmarks on the target Ryzen 5 5600G measured
approximately 25 generated tokens per second, 210 prompt tokens per second, and
1.2–2.6 seconds for typical 16–47-token realm-chat replies. The five-second
cooldown therefore remains inside measured serial inference capacity.

**Consequence:** Human activity can produce at most 12 ambient replies per
minute, regardless of the Playerbot population. Companion and ambient requests
still share one bounded inference worker, operators can lower both controls in
AI Studio, and no bot-authored message can initiate another response.

### 2026-08-31 — Keep ambient dialogue inside the player's current zone

**Decision:** Continue requiring ambient candidates to share the human player's
faction and zone, retain the 60-yard requirement for `/say`, and require the
current zone name to appear in any public-channel destination before inference.

**Reason:** Realm-wide Trade, World, or LookingForGroup reactions dilute local
zone culture and make unrelated activity follow the player. General,
LocalDefense, and nearby speech provide a focused sense of the place currently
being explored.

**Consequence:** Moving zones immediately changes both the eligible random-bot
population and prompt context. Broad public channels are dismissed without an
LLM call, while named companions remain available through whisper, party, raid,
guild, say, and explicitly addressed public chat.

### 2026-08-31 — Preserve shared city Trade ambient dialogue

**Decision:** Treat the built-in `Trade - City` channel as eligible ambient
chat in addition to `/say` and zone-named channels. Continue rejecting World,
LookingForGroup, and other public channels that are neither zone-named nor the
built-in city Trade destination.

**Reason:** General and LocalDefense represent one zone, but WoW intentionally
shares Trade across the larger trade-enabled cities. Suppressing it erased a
recognizable part of city life rather than narrowing unrelated realm-wide chat.

**Consequence:** A human who can speak in the built-in Trade channel can receive
an ambient reply there from a same-zone candidate. Moving out of a trade-enabled
city removes channel access through normal game rules; the Soul Service does not
make Trade available independently.

### 2026-08-31 — Add immediate press-and-flick controller selection

**Decision:** Preserve hold, aim, and release for bindings that expose key-down
and key-up, and add a toggle mode for `/sfc` or press-only controller mappings.
In toggle mode, moving the cursor-mapped stick past the radial threshold executes
the selected direction immediately; a second press can still confirm a partially
highlighted command.

**Reason:** Some controller mappers and action-bar macros expose only a press,
leaving the wheel open and requiring a mouse click even though the player has
already aimed at a radial command.

**Consequence:** Both input styles remain user initiated. WoW 3.3.5a still needs
the aiming stick mapped to cursor movement. The selection vector is measured from
the cursor's opening position so screen-edge wheel clamping does not skew aim.
Clients must install addon 1.2.0 once because executable addon code cannot
synchronize like companion roster data.

### 2026-08-31 — Resolve Soul Service dynamically at the HTTPS gateway

**Decision:** Configure nginx to resolve `soul-service` through Docker's embedded
DNS with a five-second validity instead of caching the container IP at gateway
startup.

**Reason:** Rebuilding Soul Service assigned a new Compose-network address while
the long-running gateway retained the old address, leaving HTTPS health checks
at 502 even after Soul Service became healthy.

**Consequence:** Future Soul Service recreation no longer requires a gateway
restart to restore the dashboard. The bridge API remains private and the gateway
continues publishing only the authenticated control plane.

### 2026-08-31 — Integrate Commander as a pinned ConsolePort client pack

**Decision:** Replace Soulforge Commander's standalone radial implementation
with a required ConsolePortLK plugin. Pin ConsolePortLK 1.5.0-rc2 at commit
`994793729ca4a5b97e87df7ce6b986ec2a370d55` and release-archive SHA-256
`9ee20bb1f3c5c5b8d45fcc5980a07bb90d49a707e120613453177c05fea6497f`.
Download it during setup into ignored runtime storage and combine its eight addon
folders with Soulforge Commander only through the authenticated local dashboard.

**Reason:** ConsolePort already owns the calibrated radial input, utility-ring
presentation, focus navigation, and controller configuration needed by the 3.3.5a
client. A plugin keeps Soulforge focused on Playerbots commands and the active
world's dynamic companion roster instead of maintaining a parallel input system.

**Consequence:** The fixed Soulforge ring contains Follow, Stay, Attack, Tank
Pull, Flee, Reset, Rebuff, and Companions; Assemble lives in the companion panel.
There is no standalone fallback wheel. Companion data still synchronizes without
a redownload, but code changes require replacing the client addon folders. The
third-party Artistic-2.0 notice remains in `ConsolePort/LICENSE.md`; GitHub Pages
documents installation but does not host the pack. Automated archive, Lua,
service, contract, and dashboard checks are required before release; physical
controller testing in a WoW client remains explicitly pending until recorded.
The cached archive is mode `0644` so the unprivileged Soul Service container can
read its bind mount without granting write access.
On 2026-08-31, `./scripts/setup-client-addons.sh` verified the exact release
archive and `./scripts/verify.sh` passed 26 Soul Service tests, 13 control-agent
tests, static-site validation, the React production build, Lua parsing, Compose
validation, and the Soulbridge C++ build/test on the current Linux host.

### 2026-09-01 — Bundle legacy WoWmapperX and bind Commander through ConsolePort

**Decision:** Add the official WoWmapperX 1.1.0 x86 NativeAOT release asset to
the authenticated client pack at `Controller/WoWmapperX`, pinned to tag commit
`89e6c8aa6f5b72b40f85d0eb413356f943f709fa` and SHA-256
`a7b60153416584fd52ff2d465cdf35f13c13554bf197e7f0edb7a1542fe676ef`.
Soulforge Commander 2.1 forces its managed ring onto ConsolePort's default
utility-ring chord (`CTRL-SHIFT-` + `CP_R_DOWN`) through
`SetupUtilityBindings`, which also refreshes ConsolePortBar. It records the
prior action and exposes `/sfc unbind` and `/sfc bind` for reversible control.

**Reason:** The legacy client does not consume modern controller input itself;
without a mapper, movement appears broken even when ConsolePort addons load.
Binding the ring only in saved ring data also left it absent from the active
ConsolePort binding set and bars.

**Consequence:** The generated pack separates addon folders from the Windows
controller executable, validates exact archive contents and PE signatures, and
preserves the MIT notice. WoWmapperX is archived and deprecated upstream in
favor of WoWpadX, is labeled accordingly, and is never auto-executed. Commander
changes only the existing utility-ring chord; `CP_L_*` movement and ordinary
action bindings remain untouched. Automated packaging and source checks do not
replace a physical controller/client smoke test, which remains pending.
On 2026-09-01, both pinned runtime archives passed checksum, path, license/API,
and executable-signature validation; `./scripts/verify.sh` passed 26 Soul Service
tests, 13 control-agent tests, Pages validation, the React build, Lua parsing,
Compose rendering, and the C++ bridge test. A live authenticated HTTPS download
returned pack 2.1.0 with all expected top-level roots, Commander 2.1, the
WoWmapperX PE payload, and its MIT notice.
