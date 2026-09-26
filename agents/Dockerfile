# Agents API + worker image. Build context = repo root (needs contracts/ for the Contract Builder).
# Run `make contracts-deps` first so contracts/lib (OpenZeppelin, forge-std) is present.
FROM python:3.12-slim

ARG FOUNDRY_VERSION=stable
ARG SOLC_VERSION=0.8.28
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 blockid

# Foundry (forge/cast): the Contract Builder runs tests + deploy dry-runs in-container
RUN mkdir -p /opt/foundry && curl -sSL \
      https://github.com/foundry-rs/foundry/releases/download/${FOUNDRY_VERSION}/foundry_${FOUNDRY_VERSION}_linux_amd64.tar.gz \
      | tar -xz -C /opt/foundry
ENV PATH="/opt/foundry:${PATH}"

WORKDIR /app
COPY agents/pyproject.toml agents/pyproject.toml
COPY agents/src agents/src
RUN pip install --no-cache-dir ./agents slither-analyzer

COPY --chown=blockid contracts contracts

USER blockid
# solc for the non-root user (forge looks in ~/.svm); compile once at build time
RUN mkdir -p /home/blockid/.svm/${SOLC_VERSION} \
    && curl -sSL -o /home/blockid/.svm/${SOLC_VERSION}/solc-${SOLC_VERSION} \
      https://github.com/ethereum/solidity/releases/download/v${SOLC_VERSION}/solc-static-linux \
    && chmod +x /home/blockid/.svm/${SOLC_VERSION}/solc-${SOLC_VERSION} \
    && cd contracts && forge build --offline

ENV PYTHONUNBUFFERED=1
