# hadolint ignore=DL3007
FROM openas2app-openas2:latest

# Copy over the specific configurations for the mock trading partner
COPY config/ /opt/openas2/config/

# Ensure the directories for data exist so we don't crash on startup
RUN mkdir -p /opt/openas2/data/outbox/FLOWWOLF_LOCAL_AS2 \
    && mkdir -p /opt/openas2/data/outbox/FLOWWOLF_AWS_AS2 \
    && mkdir -p /opt/openas2/data/inbox \
    && mkdir -p /opt/openas2/data/resend \
    && mkdir -p /opt/openas2/data/msgheaders \
    && chown -R root:root /opt/openas2/data

# The default openas2 entrypoint handles launching the JVM
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
