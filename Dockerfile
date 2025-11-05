# syntax=docker/dockerfile:1.6

##### Source stages ###########################################################

# 1) Default: use local working tree
FROM scratch AS local-src
# Copies whatever is in the build context (honors .dockerignore)
COPY . /src

# 2) Optional: fetch code from a remote repo/ref (pass SRC_STAGE=git-src)
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

# tini handles PID1/signals; git only needed at build-time for git-src;
# ca-certificates keeps TLS happy on Elastic Cloud; jq/curl handy for debugging.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tini curl jq ca-certificates libsasl2-2 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pick which source to use; default = local-src (your CWD changes)
ARG SRC_STAGE="local-src"
COPY --from=${SRC_STAGE} /src/ /app/

# Install Python deps (unchanged from your current flow)
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