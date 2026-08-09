#!/bin/sh
set -e

# The bind-mounted .wwebjs_auth/.wwebjs_cache dirs may not exist yet on the
# host, in which case Docker creates them as root before we can write to
# them as pptruser - fix ownership here (running as root) before dropping
# privileges, so this works regardless of host-side UID/permissions.
mkdir -p /usr/src/app/.wwebjs_auth /usr/src/app/.wwebjs_cache
touch /usr/src/app/instances.json
chown -R pptruser:pptruser /usr/src/app/.wwebjs_auth /usr/src/app/.wwebjs_cache /usr/src/app/instances.json

# Ensure puppeteer/cosmiconfig searches under pptruser's home, not /root.
export HOME=/home/pptruser
mkdir -p /home/pptruser/.config/puppeteer
chown -R pptruser:pptruser /home/pptruser/.config

exec setpriv --reuid=pptruser --regid=pptruser --init-groups "$@"
