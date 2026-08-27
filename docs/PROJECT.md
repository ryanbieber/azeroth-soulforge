# Azeroth Soulforge — Durable Project Specification

**Document version:** 1.6

**Status:** runnable alpha

**Last reviewed:** 2026-08-27

This document is the durable source of truth for the project. Code, contracts,
operations, and milestone claims must agree with it.

## 1. Vision and success criteria

Azeroth Soulforge enables a private solo/LAN AzerothCore realm in which one
human builds a guild of roughly 40 named Playerbot companions. Each curated
companion has a persistent simulated identity: personality, conversational
voice, relationships, memories, promises, and goals that survive restarts and
evolve from shared play.

The project uses *soul* as approachable product language for that continuity. It
does not assert consciousness, sentience, inner experience, or literal life.

The first complete release succeeds when:

- A pinned AzerothCore Playerbots fork and module build reproducibly.
- Forty curated companions can level, gear, group, and raid through Playerbots.
- Humans can interact with souls through in-game chat and a local dashboard.
- Meaningful events become attributable memories that survive restarts.
- Slow or unavailable inference never stalls the world update loop or gameplay.
- Realm phases advance sequentially only after a verified database backup.
- An eight-hour, 40-companion soak run shows no cross-soul memory leakage,
  duplicate deliveries, runaway bot conversations, or LLM-related world stalls.

## 2. Scope and non-goals

In scope: Linux source deployment for localhost or trusted LAN; AzerothCore
3.3.5a with the required Playerbots fork; about 40 soulful guild bots; in-game
chat; an authenticated LAN administration dashboard; local Ollama inference;
and manual Vanilla-to-Wrath
progression.

Not in v1: a public internet realm, cloud inference, direct LLM gameplay
control, claims of consciousness, voice chat, a custom client, or distribution
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
    |-- identity, relationships, memory, retrieval
    |-- inference scheduler and authenticated admin API
    |-- SQLite in WAL mode
    |
Ollama chat and embedding APIs

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
- **Soul Service** owns profiles, memory, relationships, prompts, inference,
  dashboard behavior, and the durable outbox.
- **React dashboard** manages non-secret bot, soul, model, and server settings
  through same-origin administration APIs.
- **Control Agent** is an internal-only, Docker-privileged allowlist for service
  state, game-server lifecycle, Playerbot roster queries, and selected configs.
- **Ollama** performs local generation and embedding behind a replaceable
  adapter and is never called from the game process.

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
are bounded per event. Structured memory extraction may produce no memory for
trivial interactions.

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

The dashboard currently supports Playerbot roster discovery; soul seeding,
editing, pausing, and per-character SKILL.md authoring; memory
inspection/deletion; service health and game-server
lifecycle; realm name and type, bot population, player-limit, bounded gameplay
rate settings; optional dedicated-character auction-house buyer/seller
automation; global
dialogue tuning; and Ollama model installation/selection. Export,
relationships/promises/goals, latency analytics, and progression workflows
remain future work. Progression controls are deliberately absent until backup
verification and restore testing are automated.

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
