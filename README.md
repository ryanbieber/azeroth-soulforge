# Azeroth Soulforge

Azeroth Soulforge is a local/private AzerothCore 3.3.5a realm where Playerbot
companions have persistent simulated identities, personalities, and memories.
Playerbots owns every gameplay action; a local Ollama service supplies social
dialogue without blocking the game world thread.

The word *soul* means a designed simulation of continuity. It is not a claim
that a bot or language model is conscious or alive.

## What works

- Pinned Playerbots AzerothCore fork, `mod-playerbots`, and
  `mod-progression-system`, compiled together in Docker.
- Level-19 initial progression phase with 50 random bots by default.
- Asynchronous C++ Soulbridge with HMAC authentication and durable reply flow.
- SQLite WAL storage for soul profiles, conversation memories, and outbox data.
- Local dialogue through Ollama and `qwen3.5:4b`.
- Loopback-only soul dashboard at <http://127.0.0.1:8765>.
- One-command whole-app lifecycle: `make up` and `make down`.

## First launch

Docker and Docker Compose are the only host build dependencies. The first run
builds AzerothCore, downloads extracted server map data, and downloads the
3.4 GB model, so it is much slower than later starts.

```bash
cp .env.example .env
# Edit .env and replace every private placeholder.
make firewall
make up
```

`make firewall` is a one-time LAN firewall step and asks for the Linux password
locally. `make up` creates or updates the game account from `.env`, imports the
databases, advertises the realm at the configured LAN address, and starts all
seven services. It does not affect unrelated Docker applications.

To stop everything while retaining databases, souls, maps, and model files:

```bash
make down
```

See [LAN launch guide](docs/LAN_SETUP.md) for client configuration and
troubleshooting. See [durable project specification](docs/PROJECT.md) for
architecture and decisions. Contributors and coding agents must read
[AGENTS.md](AGENTS.md).

Useful commands:

```bash
make status    # all container states
make logs      # follow logs
make backup    # timestamped full database dump before progression changes
make account   # recreate/update the account from .env
make verify    # repository tests and contract checks
```

## Repository layout

- `mod-soulbridge/` — asynchronous AzerothCore C++ bridge.
- `soul-service/` — local dialogue, persistence, and dashboard service.
- `contracts/` — versioned event, outbox, and export contracts.
- `config/upstreams.lock.yaml` — exact upstream source revisions.
- `scripts/` — reproducible setup, lifecycle, backup, account, and LAN tools.
- `docs/PROJECT.md` — durable source of project truth.

## Legal and data notice

This project is not affiliated with Blizzard Entertainment and does not ship a
WoW client, Blizzard game files, runtime databases, model weights, or secrets.
You must supply a legally obtained WoW 3.3.5a client for each playing computer.
Original project code is GPL-2.0-only; see [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
