# LAN Launch Guide

This guide is for the current server host at `192.168.86.139` on the
`192.168.86.0/24` home network. No router port-forwarding is needed for devices
on the same Wi-Fi/Ethernet network.

## 1. Enter private values

Edit the root `.env` file and replace all three private placeholders:

- `SOULFORGE_DB_ROOT_PASSWORD`: use a long random letters/numbers value.
- `SOULFORGE_BRIDGE_SECRET`: use another independent long random value.
- `SOULFORGE_GAME_USERNAME` and `SOULFORGE_GAME_PASSWORD`: the login used by
  the WoW client. The 3.3.5a password must be 8-16 letters/numbers.

Do not paste these values into chat or commit `.env`. The initial game account
is granted GM level 3 so the realm owner can administer the private server.

## 2. Allow local game traffic

Run once on the server host:

```bash
make firewall
```

This allows TCP `3724` (authentication) and `8085` (world) only from
`192.168.86.0/24`. The dashboard, Ollama, database, and SOAP administration
endpoint remain loopback-only.

## 3. Start the complete server

```bash
make up
```

The first run can take a while and uses several gigabytes for source, images,
server map data, databases, and `qwen3.5:4b`. Wait for `Azeroth Soulforge is
ready`. Inspect progress in another terminal with `make status` or `make logs`.

## 4. Configure each WoW client

Supply your own legally obtained World of Warcraft 3.3.5a (build 12340) client.
In its locale folder—commonly `Data/enUS/realmlist.wtf`—replace the contents
with:

```text
set realmlist 192.168.86.139
```

For another locale, use that folder, such as `Data/enGB`. Start `Wow.exe`
directly rather than a retail launcher, then sign in with the game username and
password from `.env`.

## 5. Speak with a soul

Playerbots performs normal gameplay. Whisper a Playerbot, or mention its exact
name in party/raid/guild chat. The first interaction lazily creates its soul
record. Edit its archetype, voice, and values on the server host at
<http://127.0.0.1:8765>. Memories persist in the `soul-data` Docker volume.

## Network reliability

Reserve `192.168.86.139` for this server in the router's DHCP settings. If the
host address changes, update `SOULFORGE_LAN_IP` in `.env`, run `make up` again,
and update `realmlist.wtf` on each client.

If a client cannot connect:

```bash
make status
make logs
ss -ltn | grep -E ':3724|:8085'
```

Confirm both computers are on `192.168.86.x`, guest Wi-Fi/client isolation is
disabled, and the firewall rules exist. Internet players require a separate,
security-reviewed deployment and are outside this project's scope.
