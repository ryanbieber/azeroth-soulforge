# Dashboard

The dashboard is a Vite-built React single-page application for the prompted
fresh-world experience. Home combines world lifecycle, human presence, server
health, AI state, usage, and spend; focused World, Companions, AI Studio, Client Addons,
and Advanced pages keep routine play separate from administration.
Advanced exposes bounded XP scaling from 0.1×–10× through the existing
allowlisted server-settings API; applying it persists the grouped AzerothCore
XP rates and restarts worldserver when it is running.

Client Addons reports server-side package readiness and downloads one ZIP with
the pinned ConsolePortLK modules, Soulforge Commander, and the legacy Windows
WoWmapperX controller utility. It cannot inspect a
remote WoW client's `Interface/AddOns` directory.

It never receives database, bridge, control-agent, Docker, or game-account
credentials. Production assets are compiled into the Soul Service image.

```bash
npm ci
npm run build
```
