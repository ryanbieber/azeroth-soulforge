# Start Your Own Azeroth Soulforge Server

This guide takes a new operator from a clean Linux host to a private WoW 3.3.5a
realm accessible on the same Wi-Fi or Ethernet network.

## 1. Understand the boundaries

Soulforge is intended for localhost or a trusted LAN. Do not add router
port-forwarding or expose it to the public internet. You must provide a legally
obtained World of Warcraft 3.3.5a build 12340 client; the repository cannot
provide Blizzard software or extracted game assets.

Language models supply companion dialogue and occasional ambient realm chatter
only. Playerbots controls combat, movement, quests, inventory, groups, and all
other gameplay.

## 2. Prepare the host

Use a Linux x86_64 or ARM64 computer with at least 10 GiB RAM and 15 GiB free
disk. Install:

- Docker Engine and the Docker Compose v2 plugin
- Git and Make
- OpenSSL and curl
- Python 3.8 or newer
- `iproute2` (the `ip` command)

Docker’s official installation instructions are the safest source for your
Linux distribution. Confirm Docker works without `sudo` before continuing:

```bash
docker version
docker compose version
```

## 3. Clone and configure Soulforge

```bash
git clone https://github.com/ryanbieber/azeroth-soulforge.git
cd azeroth-soulforge
cp .env.example .env
```

Run `ip -brief address` and identify the stable address on the interface used by
your home network. Avoid loopback (`127.0.0.1`) and temporary Docker addresses.
Reserve this address in your router’s DHCP settings when possible.

Edit `.env` and replace every placeholder:

| Setting | Purpose |
| --- | --- |
| `SOULFORGE_DB_ROOT_PASSWORD` | Private MariaDB administrator password |
| `SOULFORGE_BRIDGE_SECRET` | Authenticates game events to Soul Service |
| `SOULFORGE_CONTROL_SECRET` | Authenticates the internal control agent; use at least 32 characters |
| `SOULFORGE_ADMIN_PASSWORD` | Dashboard sign-in; use at least 12 characters and keep it unique |
| `SOULFORGE_SECRETS_KEY` | Encrypts provider API keys at rest; use a unique random value of at least 24 characters |
| `SOULFORGE_OPENAI_API_KEY` | Optional first-boot OpenAI key; uses paid AI for companions/directing while keeping the small ambient model local |
| `SOULFORGE_OPENAI_BASE_URL` | Optional OpenAI endpoint; a trailing `/v1` is normalized |
| `SOULFORGE_OPENAI_MODEL` | Optional first-boot OpenAI model for direction and dialogue |
| `SOULFORGE_AMBIENT_MODEL` | Local low-cost world-chat model; defaults to `qwen3:1.7b` |
| `SOULFORGE_GAME_USERNAME` | WoW client login name |
| `SOULFORGE_GAME_PASSWORD` | WoW 3.3.5a login password; 8–16 letters and numbers |
| `SOULFORGE_LAN_IP` | Stable address of the server host |
| `SOULFORGE_BIND_ADDRESS` | Set to the same address as `SOULFORGE_LAN_IP` |
| `SOULFORGE_LAN_CIDR` | Trusted home subnet, such as `192.168.1.0/24` |

Do not paste these values into an issue or commit `.env`. The file is ignored by
Git. The initial game account receives GM level 3 for private-realm ownership.

## 4. Check, authorize, and start

```bash
make doctor
make firewall
make up
```

`make doctor` validates the required tools, Docker access, architecture, RAM,
and free space. `make firewall` asks for the Linux password once and permits
ports 3724, 8085, and 8765 only from the configured trusted subnet. `make up`
starts the whole Compose application.

The first run downloads source, containers, and extracted map data, and compiles
AzerothCore. It downloads the roughly 1.4 GB ambient chat model; without a paid
provider key it also downloads the larger companion/director model. It can take considerably longer than later starts. In another
terminal, monitor it with:

```bash
make status
make logs
```

Do not interrupt database import. Wait until the launcher prints
`Azeroth Soulforge is ready`.

## 5. Open the dashboard

From a trusted device on the same LAN, visit:

```text
https://YOUR_LAN_IP:8765
```

The browser warning is expected because Soulforge generates a self-signed
certificate for the private LAN address. Verify the address before accepting
it, then sign in using `SOULFORGE_ADMIN_PASSWORD`.

On a fresh install the dashboard opens **Forge your world**. Write one world
prompt describing the tone, history, people, tensions, and social texture you
want, choose your faction and combat role, then forge. Soulforge turns that
seed into immutable canon, selects a complementary companion party, and
plans spoiler-free future threads. Once it is ready, **Enter world** starts the
game services. World time advances only while a human player is online.

The dashboard also manages bot population, companions, gameplay rates, and AI
routing. In **AI Studio**, local Ollama and paid OpenAI, Anthropic, Gemini, or
compatible providers can be configured separately for world direction and
companion dialogue, while a small local model handles zone-aware ambient chat.
The ambient route defaults to its measured maximum controls—a 25 percent reply
chance and five-second global cooldown—and can be reduced in AI Studio. It only
answers `/say` or public channels whose name contains your current zone, such as
General and LocalDefense. The shared `Trade - City` channel is also eligible
while the game makes it available in a trade-enabled city; World and
LookingForGroup do not invoke ambient AI. Provider keys are encrypted server-side
and never returned to the browser. Set an optional monthly cap and use the global
switch to stop new AI calls. Do not publish this dashboard through a router or
public tunnel.

Under **Settings → Gameplay rates**, multipliers from 0.1×–10× control XP,
reputation, item loot, money drops, and honor. Profession skill gain accepts
whole-number multipliers from 1×–10×. Applying a rate safely restarts the
worldserver; it does not unlock progression brackets or raise the bot level cap.

Under **Settings → Realm**, **New character boost level** controls the starting
level for characters created after you apply the setting. Set it to `55` when
you want new alts ready to begin endgame quest chains quickly. It applies to
normal and heroic classes, restarts the worldserver, and does not change
existing characters, gear, weapon skills, professions, flight paths, or
attunements. Return it to `1` whenever you want the ordinary starting
experience again.

Under **Settings → Auction house**, choose a dedicated unused character before
enabling the seller or buyer. Create that alt normally in the WoW client, log
it out, refresh the dashboard, and select it. Do not play the assigned
auctioneer; the module uses its identity for market operations. The seller and
buyer are disabled by default.

New installs default to 500 **Random bots**; the dashboard accepts 0–2,000.
This is a safety ceiling, not a promise that every host can run 2,000 bots
smoothly. Increase the population in steps, allow the bots to finish logging
in, and watch worldserver CPU and game latency before raising it again. Random
population bots do not automatically receive Soulforge profiles or invoke the
dialogue model.

The first `make up` automatically runs the equivalent of `make bots`: a
maintenance-only worldserver creates and logs in the configured population,
flushes its generated character state, and stops before authentication opens.
This can add several minutes to the first startup. Run `make bots` directly only
when the game services are stopped and you want to complete that preparation
separately. Normal starts keep random bots offline until a human connects, then
begin conservative background login batches after a 30-second grace period.

The database defaults to a 4 GiB InnoDB buffer pool because AzerothCore and
Playerbots quickly overwhelm MySQL's 128 MiB default. It flushes redo logs once
per second instead of forcing every bot transaction to disk. This is appropriate
for a private, restartable realm and means a host crash can lose up to the most
recent second of database work. Set `SOULFORGE_DB_BUFFER_POOL_SIZE` in `.env`
before `make up` if the host needs another cache size.

Your own normal-account characters appear first in the **All bots** roster with
a **Player-added companion** flag; generated `rndbot` characters remain in the
separate world-population section. This makes personal characters easy to find
and forge into souls without making every random world bot an LLM user.

## 6. Connect a WoW client

On every client computer, locate the locale directory—for example `Data/enUS`
or `Data/enGB`—and replace `realmlist.wtf` with:

```text
set realmlist YOUR_LAN_IP
```

Start `Wow.exe` directly rather than a modern retail launcher. Sign in with the
game username and password from `.env`. No port-forwarding is necessary when
the server and client are on the same LAN.

## 7. Command your companion party

Open **Client Addons** in the authenticated dashboard and download the single
pack. It contains pinned ConsolePortLK 1.5.0-rc2 and Soulforge Commander; it
contains no character names or credentials. Extract the ZIP first because WoW
cannot load addon ZIP files. Copy every extracted top-level addon folder directly
into `Interface/AddOns` and verify these exact paths exist with no extra parent:

```text
Interface/AddOns/ConsolePort/ConsolePort.toc
Interface/AddOns/SoulforgeCommander/SoulforgeCommander.toc
```

Fully close and restart Wow.exe, enable both addons at character selection, and
complete ConsolePort's controller calibration. WoW 3.3.5a does not natively
consume modern gamepad input, so use a controller mapper that exposes controller
buttons and sticks as keyboard/mouse input; no mapper executable is distributed
by Soulforge.

Open `/cp config`, enter ConsolePort's Ring Manager, and bind the automatically
created **Soulforge Commander** ring to one button. Hold that button, flick with
ConsolePort's radial input toward Follow, Stay, Attack, Tank Pull, Flee, Reset,
Rebuff, or Companions, and release. **Companions** opens a
controller-navigable panel that requests the active world's roster. Enable or
disable entries, choose everyone, a role, or one companion as the command target,
then choose **Assemble enabled** to invite the party. `/sfc` opens the same panel;
`/sfc sync` refreshes it and `/sfc status` prints integration diagnostics.

Future server-side companion changes sync without reinstalling or downloading
the pack. Only addon-code or pinned ConsolePort upgrades require replacing the
installed folders.

The forged companions receive deep-memory profiles automatically. Each
profile is materialized inside Soul Service as:

```text
/data/profiles/REALM/CharacterName/SKILL.md
```

The visible folder uses the current character name. Soulforge retains the
immutable AzerothCore character GUID internally so renames do not merge or
replace identities. Whisper a companion in game to exercise its dialogue and
shared world-memory flow. Additional existing Playerbots can be promoted from
**Companions**.

Soulforge does not keep every line forever. A companion keeps 60 recent chat
messages for continuity, while world conversations pass through a bounded
temporary buffer. The director periodically promotes only durable facts,
promises, relationships, discoveries, and decisions into the Chronicle.

## 8. Operate and protect the realm

Use `make down` for a normal shutdown. Databases, souls, map data, configuration,
and model files remain in named Docker volumes and are reused by `make up`.

### Macro fallback

If an addon or binding cannot be used, the General macros in [Playerbots Party
Hotkeys](PLAYERBOT_HOTKEYS.md) provide the same core orders.

Run `make backup` before any progression change. Never remove Docker volumes
unless you intend to delete the realm, and never attempt to reverse progression
with improvised SQL.

You can install a stronger Ollama model from the dashboard when the host has
enough RAM/storage. Changing models does not change companion identity.
When `SOULFORGE_OPENAI_API_KEY` is present on first boot, `make up` skips the
default model download and imports the paid profile once. Later AI Studio
provider and routing changes are not overwritten by startup.

## Troubleshooting

If the dashboard or client cannot connect:

```bash
make status
make logs
ss -ltn | grep -E ':3724|:8085|:8765'
```

Confirm:

- The host and client are on the same non-guest network.
- Wi-Fi client isolation is disabled.
- `SOULFORGE_LAN_IP` is assigned to the host.
- `SOULFORGE_BIND_ADDRESS` matches it exactly.
- `SOULFORGE_LAN_CIDR` includes the client address.
- `realmlist.wtf` contains the server address without `https://` or a port.

A fresh large Playerbot population can take several minutes to generate its
persistent character state. `make up` performs that one-time work before opening
authentication. Normal starts seed conservative 25-bot batches, a 30-second
population-manager interval, and a 250 ms bot reaction delay, and bots wait for
the human login before joining the world.

If the host IP changes, update the three LAN values in `.env`, run
`make firewall` and `make up` again, and update every client’s `realmlist.wtf`.

For architecture and current alpha limitations, see [PROJECT.md](PROJECT.md).
For host-specific notes from the original deployment, see
[LAN_SETUP.md](LAN_SETUP.md).
