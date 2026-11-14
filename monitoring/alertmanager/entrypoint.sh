#!/bin/sh
# Render alertmanager.yml from the template and the SMTP_* / ALERT_EMAIL_TO environment variables, then start.
# The SMTP password is written to a file readable only by this process (never into the config or the logs).
set -eu
umask 077
if [ -n "${SMTP_SMARTHOST:-}" ] && [ -n "${ALERT_EMAIL_TO:-}" ]; then
  receiver=email
  printf '%s' "${SMTP_PASSWORD:-}" > /tmp/smtp_password
else
  receiver=log-only
  : > /tmp/smtp_password
fi
esc() { printf '%s' "$1" | sed 's/[\/&|]/\\&/g'; }
sed -e "s|__RECEIVER__|$receiver|g" \
    -e "s|__ALERT_EMAIL_TO__|$(esc "${ALERT_EMAIL_TO:-nobody@localhost}")|g" \
    -e "s|__SMTP_FROM__|$(esc "${SMTP_FROM:-flare-alerts@localhost}")|g" \
    -e "s|__SMTP_SMARTHOST__|$(esc "${SMTP_SMARTHOST:-localhost:25}")|g" \
    -e "s|__SMTP_USERNAME__|$(esc "${SMTP_USERNAME:-}")|g" \
    /etc/alertmanager/alertmanager.yml.tmpl > /tmp/alertmanager.yml
echo "alertmanager: receiver=$receiver"
exec /bin/alertmanager --config.file=/tmp/alertmanager.yml --storage.path=/alertmanager \
  --web.external-url="${ALERTMANAGER_EXTERNAL_URL:-http://localhost:9093}" "$@"
