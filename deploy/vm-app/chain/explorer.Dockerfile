# Ping.pub open-source Cosmos explorer, built with a chain config for the BlockID chain.
FROM node:20-bookworm AS build
ARG EXPLORER_REF=master
RUN git clone https://github.com/ping-pub/explorer.git /src && cd /src && git checkout ${EXPLORER_REF}
WORKDIR /src
# Replace the bundled chain list with our chain only
RUN rm -rf chains/mainnet/* chains/testnet/*
COPY explorer/blockid.json chains/mainnet/blockid.json
# Served under https://eth.blockid.au/explorer/ (see nginx / Caddyfile), so build with that base path
RUN yarn install --frozen-lockfile && yarn build-only --base=/explorer/

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
RUN printf 'server { listen 80; root /usr/share/nginx/html; location / { try_files $uri $uri/ /index.html; } }' \
      > /etc/nginx/conf.d/default.conf
