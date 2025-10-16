# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# tini handles PID 1/signals; git only needed at build-time to clone repo;
# ca-certificates keeps TLS happy on Elastic Cloud.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git tini curl jq ca-certificates libsasl2-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone es-py repo - can override at build-time with --build-arg
ARG ES_PY_REPO="https://github.com/igsr/es-py.git"
ARG ES_PY_REF="main"
ARG ES_PY_SHA=""
RUN git clone --branch "${ES_PY_REF}" --depth 1 "${ES_PY_REPO}" . \
    && if [ -n "${ES_PY_SHA}" ]; then \
    git fetch origin "${ES_PY_SHA}" && git checkout "${ES_PY_SHA}"; \
    fi

# Install Python depenendencies
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

RUN mkdir -p /config /data /work \
    && chmod 0777 /config /data /work
ENV ESPY_CONFIG=/config/config.ini

# Non-root user
RUN useradd -m -u 10001 espy
USER espy

# Default to a shell
CMD ["/bin/bash"]