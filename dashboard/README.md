# Dashboard

The dashboard is a Vite-built React single-page application for the prompted
fresh-world experience. Home combines world lifecycle, human presence, server
health, AI state, usage, and spend; focused World, Companions, AI Studio, Addon,
and Advanced pages keep routine play separate from administration.

It never receives database, bridge, control-agent, Docker, or game-account
credentials. Production assets are compiled into the Soul Service image.

```bash
npm ci
npm run build
```
