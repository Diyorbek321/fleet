#!/usr/bin/env bash
#
# Put the demo tenant on its feet, in one command, for a customer presentation.
#
# Four people have to see something believable: the fleet owner (Telegram), the
# dispatcher (web panel), the driver (mobile app) and the cargo owner
# (Telegram). Each has its own seeder, and the order matters — the Telegram
# bindings need trips to point at, and the driver login needs a driver who is
# actually out on a run. This encodes that order so it does not have to be
# remembered on the morning of a meeting.
#
#   ./scripts/demo-setup.sh                 # rebuild the demo org, keep Telegram links
#   ./scripts/demo-setup.sh --reset-telegram  # re-mint the owner's links too
#   ./scripts/demo-setup.sh --local         # against the local Docker Postgres
#
# The fleet is rebuilt from scratch every run, deliberately and not as a
# fallback: ``seed_demo_uz.py`` without --reset collides on the first plate it
# re-inserts, and a demo wants fresh timestamps anyway — data seeded this
# morning and shown this afternoon has trucks that have not moved in six hours.
#
# The owner's Telegram chats survive that rebuild. They hold the chat id
# somebody produced by opening a magic link, and rebuilding the fleet is no
# reason to make them do it again ten minutes before a meeting. Cargo-owner
# subscriptions cannot survive it — they belong to trips that no longer exist —
# so they are re-minted and their links have to be re-opened. --reset-telegram
# clears the owner chats as well, for a demo on someone else's phone.
#
# DEMO_PASSWORD is required and is read from the environment, never from an
# argument — an argument lands in shell history on this laptop and in `ps` on
# the server. On the remote path it is piped over ssh's stdin for the same
# reason.
#
#   export DEMO_PASSWORD='...'
#   ./scripts/demo-setup.sh
#
# **Other tenants are never touched.** Every seeder here is scoped to the demo
# organization by name, and --reset only deletes rows belonging to it.
#
# On the remote path the scripts are pushed into the *running* api container
# with `docker cp` rather than baked into an image, because a full
# build-and-ship takes longer than the meeting is away. That copy lives until
# the container is recreated: after the next redeploy, run this again.
set -euo pipefail

HOST="${DEPLOY_HOST:-root@139.59.132.176}"
REMOTE_DIR="${DEPLOY_DIR:-/root/fleet}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
SSH_OPTS="-o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ConnectTimeout=20"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"

# Everything the demo needs that may not be in the deployed image yet.
FILES=(
  demo_data_uz.py
  seed_demo_uz.py
  seed_demo_driver.py
  seed_demo_telegram.py
  demo_fire.py
  simulate_live.py
)

TG_RESET=""
TARGET="remote"
for arg in "$@"; do
  case "$arg" in
    --reset-telegram) TG_RESET="--reset" ;;
    --local) TARGET="local" ;;
    -h|--help) sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }

if [ -z "${DEMO_PASSWORD:-}" ] || [ "${#DEMO_PASSWORD}" -lt 8 ]; then
  echo "DEMO_PASSWORD kerak (kamida 8 belgi):  export DEMO_PASSWORD='...'" >&2
  exit 2
fi

# --------------------------------------------------------------------------- #
# Local — straight at the Docker Postgres on :5434                             #
# --------------------------------------------------------------------------- #

if [ "$TARGET" = "local" ]; then
  PY="$BACKEND/venv/bin/python"
  [ -x "$PY" ] || PY="python3"

  say "1/4  Avtopark, reyslar, GPS, xarajatlar"
  (cd "$BACKEND" && DEMO_PASSWORD="$DEMO_PASSWORD" "$PY" seed_demo_uz.py --reset)

  say "2/4  Haydovchi ilovasi uchun login"
  (cd "$BACKEND" && DEMO_PASSWORD="$DEMO_PASSWORD" "$PY" seed_demo_driver.py)

  say "3/4  Telegram — avtopark egasi va yuk mijozi"
  (cd "$BACKEND" && "$PY" seed_demo_telegram.py $TG_RESET)

  say "4/4  Tekshiruv"
  (cd "$BACKEND" && "$PY" demo_fire.py status)
  exit 0
fi

# --------------------------------------------------------------------------- #
# Remote — the Droplet behind fleet.eduly.uz                                   #
# --------------------------------------------------------------------------- #

say "1/5  Skriptlarni serverga yuborish"
# shellcheck disable=SC2086
scp $SSH_OPTS $(printf "$BACKEND/%s " "${FILES[@]}") "$HOST:$REMOTE_DIR/" >/dev/null
echo "    ${#FILES[@]} ta fayl → $HOST:$REMOTE_DIR"

say "2/5  Ishlab turgan konteynerga ko'chirish"
ssh $SSH_OPTS "$HOST" "set -e; cd '$REMOTE_DIR'
  api=\$($COMPOSE ps -q api)
  [ -n \"\$api\" ] || { echo 'api konteyner ishlamayapti' >&2; exit 1; }
  for f in ${FILES[*]}; do docker cp \"\$f\" \"\$api:/app/\$f\"; done
  echo \"    → \$api:/app/\""

say "3/5  Ma'lumotlarni seed qilish"
# The password reaches the server on stdin, so it is absent from this laptop's
# shell history and from the ssh command line on both ends.
printf '%s\n' "$DEMO_PASSWORD" | ssh $SSH_OPTS "$HOST" "set -e
  read -r pw
  cd '$REMOTE_DIR'
  $COMPOSE exec -T -e DEMO_PASSWORD=\"\$pw\" api python seed_demo_uz.py --reset
  echo
  $COMPOSE exec -T -e DEMO_PASSWORD=\"\$pw\" api python seed_demo_driver.py"

say "4/5  Telegram obunalari va havolalari"
ssh $SSH_OPTS "$HOST" "cd '$REMOTE_DIR' && $COMPOSE exec -T api python seed_demo_telegram.py $TG_RESET"

say "5/5  Tekshiruv"
ssh $SSH_OPTS "$HOST" "cd '$REMOTE_DIR' && $COMPOSE exec -T api python demo_fire.py status"

cat <<'EOF'

Keyingi qadam — yuqoridagi havolalarni Telegramda oching:
  · avtopark egasi havolasi  → o'z telefoningizda
  · bitta yuk mijozi havolasi → ikkinchi telefonda (yoki mijozning telefonida)

So'ng xabarlarni istalgan paytda yuborish:
  ssh HOST "cd DIR && COMPOSE exec -T api python demo_fire.py owner briefing"
  ssh HOST "cd DIR && COMPOSE exec -T api python demo_fire.py customer daily"

To'liq ssenariy: docs/demo/DEMO-SCENARIY.md
EOF
