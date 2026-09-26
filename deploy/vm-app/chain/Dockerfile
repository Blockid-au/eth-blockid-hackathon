# Cosmos EVM node (evmd). Pin EVM_REF to a released tag you have tested.
FROM golang:1.25-bookworm AS build
ARG EVM_REF=v0.7.3
RUN apt-get update && apt-get install -y --no-install-recommends git make gcc && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/cosmos/evm.git /src && cd /src && git checkout ${EVM_REF}
WORKDIR /src
RUN make install

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates jq curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /go/bin/evmd /usr/local/bin/evmd
COPY init-chain.sh /usr/local/bin/init-chain.sh
RUN chmod +x /usr/local/bin/init-chain.sh
EXPOSE 26656 26657 8545 8546 1317 9090
ENTRYPOINT ["/usr/local/bin/init-chain.sh"]
