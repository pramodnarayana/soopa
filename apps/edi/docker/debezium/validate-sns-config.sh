#!/bin/sh
set -eu

: "${AWS_REGION:?AWS_REGION is required}"
: "${SNS_EDI_EVENTS_TOPIC_ARN:?SNS_EDI_EVENTS_TOPIC_ARN is required}"

case "$SNS_EDI_EVENTS_TOPIC_ARN" in
    arn:*:sns:"$AWS_REGION":*:*) ;;
    *)
        echo "SNS_EDI_EVENTS_TOPIC_ARN region must match AWS_REGION" >&2
        exit 1
        ;;
esac

if [ "$#" -eq 0 ]; then
    set -- /debezium/run.sh
fi

exec "$@"
