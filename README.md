# Azeroth Soulforge

Azeroth Soulforge is a self-hosted AzerothCore 3.3.5a realm that turns one
`w0rld` prompt into immutable canon, a fresh staged-Vanilla setting, a generated
dungeon group, persistent memories, and future narrative threads. A private
React dashboard wakes and pauses the realm, routes local or paid AI, tracks
usage, and keeps server administration out of the everyday path.

> A Soulforge “soul” is a simulation of character continuity. It is not a claim
> that a bot or language model is conscious or alive.

**[Open the illustrated setup guide](https://ryanbieber.github.io/azeroth-soulforge/)** ·
**[Detailed LAN instructions](docs/GETTING_STARTED.md)** ·
**[Report a problem](https://github.com/ryanbieber/azeroth-soulforge/issues)**

## What you need

- A Linux x86_64 or ARM64 computer on your home network.
- Docker Engine with the Compose v2 plugin, Git, Make, OpenSSL, curl, Python
  3.8+, and the Linux `ip` command.
- At least 6 GiB RAM and 15 GiB free disk; more is recommended for larger
  Ollama models.
- A legally obtained World of Warcraft 3.3.5a build 12340 client for every
  player. The repository does not provide Blizzard software or game data.
- A stable LAN address for the server. Router port-forwarding is neither needed
  nor recommended.

`make doctor` checks the host before the stack changes anything. Compilers,
MariaDB, AzerothCore, Ollama, and application libraries run in containers.

## Start your server

```bash
git clone https://github.com/ryanbieber/azeroth-soulforge.git
cd azeroth-soulforge
cp .env.example .env
```

Open `.env` and replace every placeholder. Set `SOULFORGE_LAN_IP` to this
computer’s stable Wi-Fi/Ethernet address, `SOULFORGE_BIND_ADDRESS` to the same
address, and `SOULFORGE_LAN_CIDR` to the trusted subnet. You can inspect local
addresses with `ip -brief address`.

Then run:

```bash
make doctor
make firewall
make up
```

The first launch is slow: it builds AzerothCore, initializes databases and map
data, and downloads the default 3.4 GB `qwen3.5:4b` model. Wait for
`Azeroth Soulforge is ready`.

Open `https://YOUR_LAN_IP:8765`, accept the expected self-signed certificate for
your private server, and sign in with `SOULFORGE_ADMIN_PASSWORD`.

On each WoW client, edit the locale-specific `realmlist.wtf`—for example
`Data/enUS/realmlist.wtf`—to contain:

```text
set realmlist YOUR_LAN_IP
```

Start `Wow.exe` directly and use `SOULFORGE_GAME_USERNAME` and
`SOULFORGE_GAME_PASSWORD` from your private `.env`.

## Everyday commands

```bash
make up        # check the host and start the complete application
make down      # stop it while retaining databases, souls, maps, and models
make status    # show all Soulforge containers
make logs      # follow logs
make backup    # dump all databases before progression changes
make account   # recreate or update the configured game account
make verify    # run repository tests and contract checks
```

On first use, the dashboard asks for a world prompt, faction, and intended
player role, then forges canon and a complementary companion party from the
available Playerbot roster. It can start, stop, and restart the game services; configure the
realm name and Normal/PvP/RP/RP-PvP type; choose a 1–80 starting level for new
characters; tune Playerbot population and bounded XP, reputation, loot, money,
honor, and profession rates; forge character
profiles; edit each
character’s `SKILL.md`; inspect memories; and route Ollama, OpenAI, Anthropic,
Gemini, or OpenAI-compatible models separately for world direction and dialogue.
Playerbots remains responsible for every
gameplay action—the language model is only a social layer.

The dashboard also packages **Soulforge Commander**, a 3.3.5a addon with a
hold-to-open radial command wheel. Map one button, move the mouse toward Follow,
Stay, Flee, Attack, Tank Pull, Rebuff, or Reset, and release. The installed
addon synchronizes the active world's companion roster in game and
provides a panel to enable, disable, add, or remove local entries. Companion
changes never require another download.

## Important safety notes

- This is a trusted-LAN/private-server design, not an internet deployment.
- Never commit `.env`; it and runtime credentials are ignored by Git.
- Do not expose MySQL, Ollama, Soul Service, or the internal control agent.
- Back up before changing progression. Do not improvise downgrade SQL; restore
  the complete pre-change backup after a failed unlock.
- Normal `make down` keeps named Docker volumes. Removing volumes deletes realm
  and soul data.

For the complete walkthrough, troubleshooting, IP-change procedure, and first
world instructions, read [Getting Started](docs/GETTING_STARTED.md). The
dashboard's Addon page provides Soulforge Commander; party and raid macros remain
in [Playerbots Party Hotkeys](docs/PLAYERBOT_HOTKEYS.md) as a fallback.

## Repository map

- `dashboard/` — React administration client.
- `addons/SoulforgeCommander/` — hold-to-open radial Playerbots command wheel.
- `soul-service/` — authenticated APIs, local inference, memory, and profiles.
- `mod-soulbridge/` — asynchronous AzerothCore event/reply bridge.
- `control-agent/` — internal allowlisted lifecycle/configuration boundary.
- `contracts/` — versioned public wire formats.
- `site/` — static GitHub Pages documentation.
- `docs/PROJECT.md` — durable architecture and project decisions.
- `docs/PLAYERBOT_HOTKEYS.md` — party and raid macro cheat sheet.
- `examples/profiles/Thorn/SKILL.md` — fictional companion profile example.

## Legal and project status

This project is not affiliated with Blizzard Entertainment. It does not ship a
WoW client, Blizzard game files, extracted assets, runtime databases, model
weights, or secrets. The stack is a runnable alpha; later progression unlocks
and long-duration guild soak testing are still in progress. Original project
code is GPL-2.0-only; see [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
