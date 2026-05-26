FROM python:3.12-slim-trixie AS builder

ARG WITH_MPV=0

ENV LANG C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

### Install build-time packages:
# - build-essential:    Required to compile native Python dependencies
RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . ./

RUN chmod +x docker-entrypoint.sh && \
    ./script/setup && \
    if [ "$WITH_MPV" = "1" ]; then /app/.venv/bin/pip install -e ".[mpv]"; fi


FROM python:3.12-slim-trixie

ARG WITH_MPV=0

ENV LANG C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

LABEL \
    org.opencontainers.image.authors="Open Home Foundation" \
    org.opencontainers.image.description="Voice assistant for Home Assistant" \
    org.opencontainers.image.documentation="https://github.com/OHF-Voice/linux-voice-assistant/blob/main/README.md" \
    org.opencontainers.image.licenses="Apache-2.0" \
    org.opencontainers.image.source="https://github.com/OHF-Voice/linux-voice-assistant" \
    org.opencontainers.image.title="Linux-Voice-Assistant" \
    org.opencontainers.image.url="https://github.com/OHF-Voice/linux-voice-assistant"

### Install runtime packages:
# - libpulse0:          Runtime library used by soundcard
# - libsndfile1:        Runtime library used by soundfile
# - libmpv2:            Optional runtime library required when MPV backend is enabled
# - ca-certificates:    For encrypted connections
# - procps:             For pgrep in healthcheck
RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
    libpulse0 \
    libsndfile1 \
    $(if [ "$WITH_MPV" = "1" ]; then echo libmpv2; fi) \
    ca-certificates \
    procps && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY . ./

RUN chmod +x docker-entrypoint.sh

### Set ports for ESPHome API:
EXPOSE 6053

### Set start script:
ENTRYPOINT ["./docker-entrypoint.sh"]
