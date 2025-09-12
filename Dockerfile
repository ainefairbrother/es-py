FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install git to clone repo
RUN apt-get update && apt-get install -y --no-install-recommends \
    git tini \
    && rm -rf /var/lib/apt/lists/*

# Clone the es-py repo (specify branch with ES_PY_REF arg)
WORKDIR /app
ARG ES_PY_REF=main
# RUN git clone https://github.com/igsr/es-py.git . \
#     && git fetch --depth 1 origin ${ES_PY_REF} || true \
#     && (git checkout ${ES_PY_REF} || true)
RUN git clone https://github.com/ainefairbrother/es-py.git . \
    && git fetch --depth 1 origin ${ES_PY_REF} || true \
    && (git checkout ${ES_PY_REF} || true)

# Install Python deps from the repo
RUN pip install -r requirements.txt

# Create a non-root user to run the application
RUN useradd -m -u 10001 espy
USER espy

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash"]