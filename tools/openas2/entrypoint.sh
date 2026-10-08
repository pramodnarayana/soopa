#!/bin/bash
set -e

echo "Starting Mock OpenAS2 Partner..."


# The default openas2 image runs /opt/openas2/bin/start-openas2.sh
exec /opt/openas2/bin/start-openas2.sh
