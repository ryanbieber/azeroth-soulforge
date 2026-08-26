# Local AzerothCore runtime

This directory is the ignored local runtime boundary used by `make up`. It must
be populated from a locally built, pinned Playerbots AzerothCore installation;
game binaries and extracted data are never committed.

Expected layout:

```text
runtime/azerothcore/
  bin/authserver
  bin/worldserver
  etc/authserver.conf
  etc/worldserver.conf
  etc/modules/playerbots.conf
  etc/modules/soulbridge.conf
  data/dbc/
  data/maps/
  data/vmaps/
  data/mmaps/
```

Configure both server files to use MariaDB at `127.0.0.1` and the port and
credentials from the root `.env`. Configure `DataDir` for this directory's
`data` folder. The preflight intentionally refuses to start a partial runtime.
