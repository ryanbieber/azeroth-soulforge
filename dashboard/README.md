# Dashboard

The dashboard is a Vite-built React single-page application for trusted-LAN
administration. It manages the Playerbot roster, forged soul profiles, memories,
service lifecycle, validated realm and gameplay-rate settings, and locally installed Ollama
models through same-origin `/admin/v1` APIs.

It never receives database, bridge, control-agent, Docker, or game-account
credentials. Production assets are compiled into the Soul Service image.

```bash
npm ci
npm run build
```
