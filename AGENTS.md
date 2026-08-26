# Agent Working Agreement

These instructions apply to the entire repository.

## Start here

Before changing anything:

1. Read `docs/PROJECT.md` completely.
2. Read the README for every component being changed.
3. Read the schemas in `contracts/` before changing an interface.
4. Inspect the working tree and preserve unrelated user changes.

`docs/PROJECT.md` is the durable source of truth. Update it in the same change
whenever architecture, interfaces, dependencies, operational behavior, safety
boundaries, or milestone status changes. Record substantial decisions in its
append-only decision log.

## Non-negotiable invariants

- Never perform an Ollama, HTTP, database, filesystem, or other blocking call
  on AzerothCore's world update thread.
- The LLM is a social layer. It must not directly issue Playerbots commands or
  control combat, movement, inventory, talents, quests, or group membership.
- A soul is keyed by realm ID plus immutable AzerothCore character GUID. Names
  are display data and must never be identity keys.
- Canonical profile facts override generated or summarized memories.
- Generated bot messages must carry trace metadata and must not produce an
  unlimited bot-to-bot reply chain.
- Progression changes require a verified backup. Never attempt to reverse an
  applied phase using improvised SQL; restore the complete snapshot.
- Do not describe simulated souls as conscious, sentient, or actually alive.

## Public-repository hygiene

Never commit:

- Credentials, tokens, `.env` files, real connection strings, or private keys.
- WoW clients, maps, vmaps, mmaps, DBC files, extracted assets, or database
  dumps.
- Runtime SQLite databases, backups, logs, transcripts, soul exports, generated
  memories, or private player data.
- Ollama storage, GGUF/model weights, or other large generated artifacts.

Examples must use obviously fake secrets and non-personal sample data. Preserve
third-party copyright and license notices. Pin upstream revisions in
`config/upstreams.lock.yaml`; mark them `untested` until a documented build or
integration run proves compatibility.

## Interfaces and compatibility

- Treat `contracts/openapi.yaml` and JSON schemas as public interfaces.
- Make additive changes where possible. For breaking changes, introduce a new
  API or schema version and document migration behavior.
- Event ingestion is idempotent by `event_id`. Reply delivery is at-least-once
  until acknowledged, so consumers must deduplicate by reply ID.
- Validate realm IDs, GUIDs, sizes, timestamps, destinations, expirations, and
  trace hop counts at trust boundaries.

## Change and verification protocol

- Keep the C++ bridge, Python service, contracts, and documentation consistent.
- Add or update tests for every behavior change.
- Run `./scripts/verify.sh` before handoff. Run component-specific integration
  tests when dependencies are available.
- Do not label an upstream combination as tested without recording the command,
  revision, environment, date, and result in `docs/PROJECT.md`.
- Keep commits reviewable and explain the reason for non-obvious changes.
- Avoid destructive Git and database operations. Do not alter or delete user
  data to make a test pass.

## Component boundaries

- `mod-soulbridge` captures approved world events, queues them off-thread, and
  safely delivers acknowledged chat replies back on the world thread.
- `soul-service` owns personality prompts, memory, relationships, retrieval,
  inference scheduling, dashboard behavior, and the durable outbox.
- `contracts` owns shared wire formats; neither component may invent a divergent
  private version.
- Playerbots remains authoritative for gameplay. The Soul Service may express a
  preference or suggestion only as dialogue.
