#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
COMPOSE=${COMPOSE:-docker compose}
SQL_DIR=runtime/source/azerothcore/modules/mod-ah-bot/data/sql/db-world

for file in mod_auctionhousebot.sql z_filter_disabled_and_trash.sql auctionhousebot_professionItems.sql; do
  test -s "$SQL_DIR/$file" || { echo "missing Auction House Bot SQL: $SQL_DIR/$file" >&2; exit 1; }
done

mysql_world() {
  $COMPOSE exec -T ac-database sh -lc \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --batch --skip-column-names --user=root acore_world'
}

mysql_world <<'SQL'
CREATE TABLE IF NOT EXISTS soulforge_module_migrations (
  migration varchar(100) NOT NULL PRIMARY KEY,
  applied_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
SQL

if test "$(printf '%s\n' "SELECT COUNT(*) FROM soulforge_module_migrations WHERE migration='mod-ah-bot-base-v1';" | mysql_world)" = 1; then
  echo "module SQL: mod-ah-bot base already applied"
  exit 0
fi

existing=$(printf '%s\n' "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='acore_world' AND table_name IN ('mod_auctionhousebot','mod_auctionhousebot_disabled_items','auctionhousebot_professionItems');" | mysql_world)
if test "$existing" = 3; then
  printf '%s\n' "INSERT INTO soulforge_module_migrations (migration) VALUES ('mod-ah-bot-base-v1');" | mysql_world
  echo "module SQL: adopted existing complete mod-ah-bot schema"
  exit 0
fi
if test "$existing" != 0; then
  echo "module SQL: partial mod-ah-bot schema detected; refusing a destructive repair" >&2
  exit 1
fi

for file in mod_auctionhousebot.sql z_filter_disabled_and_trash.sql auctionhousebot_professionItems.sql; do
  echo "module SQL: applying $file"
  mysql_world < "$SQL_DIR/$file"
done

printf '%s\n' "INSERT INTO soulforge_module_migrations (migration) VALUES ('mod-ah-bot-base-v1');" | mysql_world
echo "module SQL: mod-ah-bot base applied"
