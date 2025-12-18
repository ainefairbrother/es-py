# syntax=docker/dockerfile:1.6

##### Source stages ###########################################################

# 1) Default: use local working tree (honors .dockerignore)
FROM scratch AS local-src
COPY . /src

# 2) Optional: fetch code from a remote repo/ref
FROM alpine/git:latest AS git-src
WORKDIR /src
ARG ES_PY_REPO="https://github.com/igsr/es-py.git"
ARG ES_PY_REF="main"
ARG ES_PY_SHA=""
RUN git clone --branch "${ES_PY_REF}" --depth 1 "${ES_PY_REPO}" . \
    && if [ -n "${ES_PY_SHA}" ]; then \
    git fetch origin "${ES_PY_SHA}" && git checkout "${ES_PY_SHA}"; \
    fi

##### Final image #############################################################

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# tini handles PID1/signals; ca-certs for Elastic Cloud; jq/curl useful for debug
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini curl jq ca-certificates libsasl2-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build-time switch: 0=use local working tree (default), 1=use git clone
ARG USE_GIT=0

# Bring both sources into the image, then choose one
COPY --from=local-src /src/ /tmp/src/local/
COPY --from=git-src   /src/ /tmp/src/git/

# Select source into /app (then clean up temp)
RUN if [ "${USE_GIT}" = "1" ]; then \
    cp -a /tmp/src/git/. /app/ ; \
    else \
    cp -a /tmp/src/local/. /app/ ; \
    fi && rm -rf /tmp/src

# Install Python deps
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Writable dirs + default ESPY_CONFIG path
RUN mkdir -p /config /data /work \
    && chmod 0777 /config /data /work
ENV ESPY_CONFIG=/config/config.ini

# Non-root user
RUN useradd -m -u 10001 espy
USER espy

# Default to a shell
CMD ["/bin/bash"]