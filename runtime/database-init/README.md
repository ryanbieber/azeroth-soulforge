# Database initialization boundary

Place local AzerothCore and Playerbots initialization SQL here only when
assembling a fresh private runtime. SQL and database dumps in this directory are
ignored by Git. MariaDB executes eligible files only when its named data volume
is first created.

Prefer AzerothCore's supported database updater and document the exact pinned
procedure during the compatibility milestone. Never commit populated realm data.
