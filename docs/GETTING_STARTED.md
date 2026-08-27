# Start Your Own Azeroth Soulforge Server

This guide takes a new operator from a clean Linux host to a private WoW 3.3.5a
realm accessible on the same Wi-Fi or Ethernet network.

## 1. Understand the boundaries

Soulforge is intended for localhost or a trusted LAN. Do not add router
port-forwarding or expose it to the public internet. You must provide a legally
obtained World of Warcraft 3.3.5a build 12340 client; the repository cannot
provide Blizzard software or extracted game assets.

The local language model supplies companion dialogue only. Playerbots controls
combat, movement, quests, inventory, groups, and all other gameplay.

## 2. Prepare the host

Use a Linux x86_64 or ARM64 computer with at least 6 GiB RAM and 15 GiB free
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

The first run downloads source, containers, extracted map data, and the default
3.4 GB model, and compiles AzerothCore. It can take considerably longer than
later starts. In another terminal, monitor it with:

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

The dashboard manages game-service lifecycle, realm name and
Normal/PvP/RP/RP-PvP type, bot population, bounded gameplay rates, soul
profiles, memories, character `SKILL.md` guidance, and installed
Ollama models. Do not publish this dashboard through a router or public tunnel.

Under **Settings → Gameplay rates**, multipliers from 0.1×–10× control XP,
reputation, item loot, money drops, and honor. Profession skill gain accepts
whole-number multipliers from 1×–10×. Applying a rate safely restarts the
worldserver; it does not unlock progression brackets or raise the bot level cap.

Under **Settings → Auction house**, choose a dedicated unused character before
enabling the seller or buyer. Create that alt normally in the WoW client, log
it out, refresh the dashboard, and select it. Do not play the assigned
auctioneer; the module uses its identity for market operations. The seller and
buyer are disabled by default.

The **Random bots** setting accepts 0–2,000. This is a safety ceiling, not a
promise that every host can run 2,000 bots smoothly. Increase the population in
steps, allow the bots to finish logging in, and watch worldserver CPU and game
latency before raising it again. Random population bots do not automatically
receive Soulforge profiles or invoke the dialogue model.

## 6. Connect a WoW client

On every client computer, locate the locale directory—for example `Data/enUS`
or `Data/enGB`—and replace `realmlist.wtf` with:

```text
set realmlist YOUR_LAN_IP
```

Start `Wow.exe` directly rather than a modern retail launcher. Sign in with the
game username and password from `.env`. No port-forwarding is necessary when
the server and client are on the same LAN.

## 7. Forge the first companion

Open **Bots** in the dashboard to see generated Playerbots. Choose a named bot,
forge its soul, and edit its canonical voice, values, and owner-editable
character guidance. Each profile is materialized inside Soul Service as:

```text
/data/profiles/REALM/CharacterName/SKILL.md
```

The visible folder uses the current character name. Soulforge retains the
immutable AzerothCore character GUID internally so renames do not merge or
replace identities. Whisper the bot in game to exercise its local dialogue and
memory flow.

## 8. Operate and protect the realm

Use `make down` for a normal shutdown. Databases, souls, map data, configuration,
and model files remain in named Docker volumes and are reused by `make up`.

Run `make backup` before any progression change. Never remove Docker volumes
unless you intend to delete the realm, and never attempt to reverse progression
with improvised SQL.

You can install a stronger Ollama model from the dashboard when the host has
enough RAM/storage. Changing models does not change companion identity.

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

If the host IP changes, update the three LAN values in `.env`, run
`make firewall` and `make up` again, and update every client’s `realmlist.wtf`.

For architecture and current alpha limitations, see [PROJECT.md](PROJECT.md).
For host-specific notes from the original deployment, see
[LAN_SETUP.md](LAN_SETUP.md).
