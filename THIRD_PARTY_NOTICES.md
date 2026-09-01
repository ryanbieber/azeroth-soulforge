# Third-Party Notices

This repository is an independent integration project. Except for the locally
assembled client-addon pack described below, it does not vendor the projects or
model weights listed here. Operators must review the license attached to the
exact revision or model tag they use.

| Dependency | Purpose | Upstream license at planning time |
| --- | --- | --- |
| AzerothCore | WoW 3.3.5a server core | GPL-2.0 |
| mod-playerbots AzerothCore fork | Required core fork | GPL-2.0 |
| mod-playerbots | Gameplay bot module | GPL-2.0 |
| mod-progression-system | Optional phased content | Verify pinned revision |
| mod-ah-bot | Auction-house seller and buyer simulation | GPL-2.0 |
| Ollama | Local model runtime | Verify installed release |
| Qwen3.5 model | Default dialogue model | Apache-2.0 on referenced Ollama tag |
| EmbeddingGemma | Default embedding model | Model-specific Gemma terms |
| React and React DOM | Administration UI | MIT |
| Vite and React plugin | Administration UI build | MIT |
| nginx | HTTPS reverse proxy | 2-clause BSD |
| Docker CLI image | Internal control client | Apache-2.0 |
| ConsolePortLK 1.5.0-rc2 | WoW 3.3.5a controller UI bundled at setup time | Artistic-2.0; notice retained at `ConsolePort/LICENSE.md` |

`scripts/setup-client-addons.sh` downloads the unmodified ConsolePortLK
1.5.0-rc2 release archive from its upstream GitHub release and accepts only
SHA-256 `9ee20bb1f3c5c5b8d45fcc5980a07bb90d49a707e120613453177c05fea6497f`.
The archive is not tracked in Git. The authenticated local dashboard combines
it with Soulforge Commander while preserving the upstream license; the public
GitHub Pages site does not host the binary pack.

The dashboard may install other Ollama model tags at the operator's request.
Operators must review the license and usage terms attached to every selected
model; installing a model does not change this project's license.

World of Warcraft and Blizzard Entertainment are trademarks or registered
trademarks of Blizzard Entertainment, Inc. This project is not affiliated with,
endorsed by, or sponsored by Blizzard Entertainment.

Before any release containing copied or linked third-party material, regenerate
this table from the pinned revisions and include every required notice.
