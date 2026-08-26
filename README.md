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
- Local dialogue through Ollama, defaulting to `qwen3.5:4b` with runtime model
  installation and selection for more powerful hosts.
- Password-protected React control plane over HTTPS on the trusted LAN.
- Bot roster, soul profiles, memory correction, server health/lifecycle, realm
  name, population, player-limit, and inference settings in one UI.
- A name-based `SKILL.md` for every companion, combining owner-written character
  depth with a service-managed canonical profile and memory ledger.
- One-command whole-app lifecycle: `make up` and `make down`.

## First launch

`make up` checks the small host dependency set before changing anything: Linux,
Git, Make, OpenSSL, curl, Python 3.8+, `ip`, Docker Engine, Compose v2, RAM, and free disk.
All compilers and application libraries run inside containers. The first run
builds AzerothCore, downloads extracted server map data, and downloads the
3.4 GB model, so it is much slower than later starts.

```bash
cp .env.example .env
# Edit .env and replace every private placeholder.
make firewall
make up
```

`make firewall` is a one-time LAN firewall step and asks for the Linux password
locally. `make up` creates or updates the game account from `.env`, generates a
private HTTPS certificate, imports the databases, advertises the realm at the
configured LAN address, and starts the complete stack. It does not affect
unrelated Docker applications.

Open `https://YOUR_LAN_IP:8765` from a device on the configured LAN. The first
visit shows a warning because the certificate is locally generated; verify the
displayed IP before accepting it. Sign in with `SOULFORGE_ADMIN_PASSWORD`.

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
make doctor    # host dependency and capacity check
make logs      # follow logs
make backup    # timestamped full database dump before progression changes
make account   # recreate/update the account from .env
make verify    # repository tests and contract checks
```

The repository includes a seeded companion example at
`examples/profiles/Thorn/SKILL.md`. With Ollama running and `qwen3.5:4b`
installed, this command sends a signed whisper through the real Soul Service
worker and fails unless the model recalls Thorn's profile-only keepsake:

```bash
./scripts/validate-skill-inference.py
```

This model-backed check is intentionally separate from `make verify` so routine
CI does not download model weights. Souls created in the dashboard get their
own live file at `/data/profiles/REALM/CharacterName/SKILL.md` inside Soul
Service; edit them through the dashboard so SQLite and the materialized file
remain synchronized.

## Repository layout

- `mod-soulbridge/` — asynchronous AzerothCore C++ bridge.
- `soul-service/` — local dialogue, persistence, and dashboard service.
- `dashboard/` — React administration client built into Soul Service.
- `control-agent/` — internal allowlisted game/container control boundary.
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
