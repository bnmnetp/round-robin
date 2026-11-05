#!/bin/sh
# One-time setup of a fresh Ubuntu server. Run from your machine:
#   ssh root@HOST 'sh -s -- DOMAIN' < deploy/setup-server.sh
# Installs Docker, adds swap, turns on the firewall (ssh + web only), and
# creates /opt/rr/.env with a generated organizer password and secret key.
set -eu
DOMAIN=${1:?usage: setup-server.sh DOMAIN}
export DEBIAN_FRONTEND=noninteractive

if ! swapon --show | grep -q /swapfile; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 sqlite3 >/dev/null
systemctl enable --now docker >/dev/null

ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null

mkdir -p /opt/rr
if [ ! -f /opt/rr/.env ]; then
    password=$(openssl rand -base64 12 | tr -d '/+=')
    umask 077
    cat > /opt/rr/.env <<ENV
RR_DOMAIN=$DOMAIN
RR_ADMIN_PASSWORD=$password
RR_SECRET_KEY=$(openssl rand -hex 32)
ENV
    echo "Organizer password: $password  (change it in /opt/rr/.env)"
fi
echo "Server ready."
