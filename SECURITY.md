# Security Policy

## Supported versions

The project is pre-release. Security fixes are applied to the `main` branch.

## Reporting

Do not open a public issue for a vulnerability that exposes credentials,
private conversations, player data, or remote code execution. Use GitHub's
private vulnerability reporting feature when it is enabled for the repository.

## Deployment boundary

The intended initial deployment is localhost or a trusted LAN. The Soul Service
and Ollama must bind to loopback by default. LAN exposure requires explicit
configuration, authentication, and firewall rules. Never expose AzerothCore
administration ports, MariaDB, Ollama, or an unauthenticated dashboard directly
to the internet.

All bridge requests must eventually use request signing, replay protection,
strict validation, and size limits. Example secrets in this repository are not
safe for production.
