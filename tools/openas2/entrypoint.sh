#!/bin/bash
set -e

echo "Starting Mock OpenAS2 Partner..."

if [ -n "$FLOWWOLF_AS2_URL" ]; then
    RESOLVED_URL=$(printf '%s\n' "$FLOWWOLF_AS2_URL" | sed -E \
        -e 's#^([a-zA-Z][a-zA-Z0-9+.-]*://([^@/]+@)?)(localhost|127\.0\.0\.1)([:/?#]|$)#\1host.docker.internal\4#')
    ESCAPED_URL=$(printf '%s\n' "$RESOLVED_URL" | sed -e 's/\\/\\\\/g; s/|/\\|/g; s/&/\\&/g')
    sed -i "s|__FLOWWOLF_AS2_URL_PLACEHOLDER__|${ESCAPED_URL}|g" /opt/openas2/config/partnerships.xml
    echo "Configured OpenAS2 target AS2 URL: $RESOLVED_URL"
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# The default openas2 image runs /opt/openas2/bin/start-openas2.sh
exec /opt/openas2/bin/start-openas2.sh
