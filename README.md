# Azeroth Soulforge

Azeroth Soulforge is an open-source foundation for a private AzerothCore realm
where a player builds a persistent guild of Playerbot companions. AzerothCore
and Playerbots retain control of gameplay; a local Ollama-backed service gives
selected companions consistent personalities, relationships, conversation, and
long-term memory.

> **Project status:** design and integration scaffold. This repository does not
> yet provide a runnable game server.

The word *soul* in this project means a deliberately designed, persistent
simulation of identity. It is not a claim that an LLM or bot is conscious.

## Design goals

- A private solo/LAN realm with a curated guild of about 40 companions.
- Playerbots for combat, movement, questing, gearing, and raids.
- A local LLM social layer that never blocks AzerothCore's world thread.
- Durable memories keyed to immutable character GUIDs.
- Manual, backed-up Vanilla-to-Wrath realm progression.
- No cloud dependency during normal play.

Read the [durable project specification](docs/PROJECT.md) for the architecture,
operating rules, milestones, and current decisions. Contributors and coding
agents must also read [AGENTS.md](AGENTS.md).

## Repository layout

- `mod-soulbridge/` — AzerothCore C++ integration boundary.
- `soul-service/` — local Python service, memory store, and future dashboard.
- `contracts/` — versioned wire and export formats.
- `config/` — safe example configuration and upstream revision records.
- `scripts/verify.sh` — repository verification entrypoint.

## Quick verification

```bash
./scripts/verify.sh
```

## Start and stop the whole application

After completing the runtime layout in `runtime/azerothcore/` and creating a
private `.env` from `.env.example`, one command controls MariaDB, Ollama, the
Soul Service, AzerothCore authserver, and AzerothCore worldserver:

```bash
make up
make down
```

`make up` performs a full preflight, starts containerized infrastructure, then
starts the locally built Playerbots servers. If either game server fails, it
stops the infrastructure rather than leaving half the application running.
`make down` stops the game servers first and then the infrastructure. MariaDB
and Ollama data remain in named volumes.

The project uses native Playerbots server binaries because that is the supported
deployment baseline. See `runtime/azerothcore/README.md` for the required local
layout. Until that compatibility/build milestone is completed, `make dev-up`
starts only MariaDB, Ollama, and the scaffold Soul Service for development.

On first use, download the models explicitly with `make models`; downloads are
not a startup side effect. Use `make status` or `make logs` for infrastructure.

The current service exposes only `GET /health`. Versioned bridge endpoints are
contracted but intentionally return 404 until their implementation milestone.

The initial scaffold uses only the Python standard library at runtime and in
tests. FastAPI, Ollama integration, SQLite persistence, and the AzerothCore
module are planned milestones rather than mocked production features.

## Legal and data notice

This project is not affiliated with or endorsed by Blizzard Entertainment.
World of Warcraft is a trademark of Blizzard Entertainment. This repository
does not include a game client, maps, DBC files, extracted game data, database
dumps, model weights, or other proprietary assets. Operators are responsible
for complying with the laws and license terms that apply to them.

Original project code is licensed under GPL-2.0-only. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
