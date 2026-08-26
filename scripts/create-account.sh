#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
set -a; . ./.env; set +a

[[ ${SOULFORGE_GAME_USERNAME:-} =~ ^[A-Za-z0-9]{1,17}$ ]] || { echo "invalid SOULFORGE_GAME_USERNAME" >&2; exit 1; }
[[ ${SOULFORGE_GAME_PASSWORD:-} =~ ^[A-Za-z0-9]{8,16}$ ]] || { echo "game password must be 8-16 letters/numbers" >&2; exit 1; }

sql=$(python3 - <<'PY'
import hashlib, os, secrets
username = os.environ["SOULFORGE_GAME_USERNAME"].upper()
password = os.environ["SOULFORGE_GAME_PASSWORD"].upper()
salt = secrets.token_bytes(32)
inner = hashlib.sha1(f"{username}:{password}".encode()).digest()
x = int.from_bytes(hashlib.sha1(salt + inner).digest(), "little")
modulus = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
verifier = pow(7, x, modulus).to_bytes(32, "little")
print(f"INSERT INTO account(username,salt,verifier,expansion,reg_mail,email) VALUES('{username}',UNHEX('{salt.hex()}'),UNHEX('{verifier.hex()}'),2,'','') ON DUPLICATE KEY UPDATE salt=VALUES(salt),verifier=VALUES(verifier),expansion=2;")
print(f"INSERT INTO account_access(id,gmlevel,RealmID,comment) SELECT id,3,-1,'Soulforge owner' FROM account WHERE username='{username}' ON DUPLICATE KEY UPDATE gmlevel=3;")
print("INSERT IGNORE INTO realmcharacters(realmid,acctid,numchars) SELECT r.id,a.id,0 FROM realmlist r CROSS JOIN account a;")
PY
)
docker compose exec -T ac-database mysql --user=root --password="$SOULFORGE_DB_ROOT_PASSWORD" acore_auth --execute="$sql"
echo "account: ${SOULFORGE_GAME_USERNAME^^} created/updated as the local administrator"
