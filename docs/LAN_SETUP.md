# LAN Launch Guide

This guide is for the current server host at `192.168.86.139` on the
`192.168.86.0/24` home network. No router port-forwarding is needed for devices
on the same Wi-Fi/Ethernet network.

## 1. Enter private values

Edit the root `.env` file and replace every private placeholder:

- `SOULFORGE_DB_ROOT_PASSWORD`: use a long random letters/numbers value.
- `SOULFORGE_BRIDGE_SECRET`: use another independent long random value.
- `SOULFORGE_CONTROL_SECRET`: use a third independent value of at least 32
  characters. It authenticates the internal allowlisted control agent.
- `SOULFORGE_ADMIN_PASSWORD`: use a strong password of at least 12 characters.
  This signs into the React dashboard and must differ from the other secrets.
- `SOULFORGE_GAME_USERNAME` and `SOULFORGE_GAME_PASSWORD`: the login used by
  the WoW client. The 3.3.5a password must be 8-16 letters/numbers.

Do not paste these values into chat or commit `.env`. The initial game account
is granted GM level 3 so the realm owner can administer the private server.

## 2. Allow local game traffic

Run once on the server host:

```bash
make firewall
```

This allows TCP `3724` (authentication), `8085` (world), and `8765` (HTTPS
dashboard) only from `SOULFORGE_LAN_CIDR`. Ollama, MySQL, SOAP, Soul Service,
and the Docker control agent have no LAN-facing ports.

## 3. Start the complete server

```bash
make up
```

The first run can take a while and uses several gigabytes for source, images,
server map data, databases, and `qwen3.5:4b`. Wait for `Azeroth Soulforge is
ready`. Inspect progress in another terminal with `make status` or `make logs`.

## 4. Open the React control plane

From any trusted device on the same Wi-Fi or Ethernet network, open:

```text
https://192.168.86.139:8765
```

The first visit displays a browser warning because `make up` creates a private,
self-signed certificate for the configured LAN IP. Verify that the address is
your server, accept the certificate for this LAN, and sign in using
`SOULFORGE_ADMIN_PASSWORD`.

The dashboard can list all generated random Playerbots; forge, edit, pause, and
inspect their souls; delete incorrect memories; start/stop/restart the game
servers; adjust realm name, bot population and player limit; and install or
activate any Ollama model the host can run. Larger models require more RAM,
storage, and inference time. Progression unlocks remain intentionally locked
until automatic backup verification exists.

## 5. Configure each WoW client

Supply your own legally obtained World of Warcraft 3.3.5a (build 12340) client.
In its locale folder—commonly `Data/enUS/realmlist.wtf`—replace the contents
with:

```text
set realmlist 192.168.86.139
```

For another locale, use that folder, such as `Data/enGB`. Start `Wow.exe`
directly rather than a retail launcher, then sign in with the game username and
password from `.env`.

## 6. Speak with a soul

Playerbots performs normal gameplay. Whisper a Playerbot, or mention its exact
name in party/raid/guild chat. The first interaction lazily creates its soul
record. Manage it from the React control plane. Memories persist in the
`soul-data` Docker volume.

## Network reliability

Reserve `192.168.86.139` for this server in the router's DHCP settings. If the
host address changes, update `SOULFORGE_LAN_IP`, `SOULFORGE_BIND_ADDRESS`, and
`SOULFORGE_LAN_CIDR` in `.env`, run `make firewall` and `make up` again, and
update `realmlist.wtf` on each client. The HTTPS certificate is regenerated for
the new address. Binding to the specific LAN address avoids publishing game or
dashboard ports on unrelated host interfaces.

If a client cannot connect:

```bash
make status
make logs
ss -ltn | grep -E ':3724|:8085'
```

Confirm both computers are on `192.168.86.x`, guest Wi-Fi/client isolation is
disabled, and the firewall rules exist. Internet players require a separate,
security-reviewed deployment and are outside this project's scope.
