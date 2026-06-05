FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install pack CLI for Cloud Native Buildpacks.
# Task 16 / fix #4.4: Kaniko removed. pack is fully rootless and handles
# both Dockerfile and non-Dockerfile repos via its own detection logic.
ARG PACK_VERSION=v0.33.2
RUN curl -sSL "https://github.com/buildpacks/pack/releases/download/${PACK_VERSION}/pack-${PACK_VERSION}-linux.tgz" \
    | tar -C /usr/local/bin/ --no-same-owner -xzv pack

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
