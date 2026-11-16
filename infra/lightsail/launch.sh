#!/bin/bash
# Lightsail launch script (runs once as root on first boot): Docker Engine + Compose from the Ubuntu archive, a 2 GB
# swap file as a safety net for the 4 GB plan, automatic security updates, and the ubuntu user in the docker group.
set -eux
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 unattended-upgrades curl
systemctl enable --now docker
usermod -aG docker ubuntu
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
mkdir -p /opt/flare && chown ubuntu:ubuntu /opt/flare
touch /var/lib/flare-launch-done
