#!/bin/bash
set -e

echo "Starting Mock OpenAS2 Partner..."

if [ -n "$FLOWWOLF_AS2_URL" ]; then
    sed -i "s|__FLOWWOLF_AS2_URL_PLACEHOLDER__|${FLOWWOLF_AS2_URL}|g" /opt/openas2/config/partnerships.xml
fi

# The default openas2 image runs /opt/openas2/bin/start-openas2.sh
exec /opt/openas2/bin/start-openas2.sh
