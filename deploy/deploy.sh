#!/bin/sh
# Deploy the committed code (HEAD) to the server and restart it.
#   deploy/deploy.sh [root@HOST]
# The database lives in a Docker volume and survives deploys.
set -eu
HOST=${1:-root@pickle.millercabin.com}
cd "$(dirname "$0")/.."
git diff --quiet HEAD -- || echo "Note: uncommitted changes are not deployed." >&2

git archive --format=tar HEAD | ssh "$HOST" 'set -eu
cd /opt/rr
rm -rf app.new
mkdir app.new
tar -x -C app.new
ln -s /opt/rr/.env app.new/deploy/.env
rm -rf app.old
[ -d app ] && mv app app.old
mv app.new app
cd app/deploy
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
docker compose ps'
