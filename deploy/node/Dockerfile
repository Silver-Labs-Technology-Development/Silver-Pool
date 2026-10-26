# syntax=docker/dockerfile:1.7
FROM ubuntu:22.04

ARG BTCS_VERSION=31.1.3
ARG BTCS_RELEASE_URL=https://github.com/bitcoin-silver/core/releases/download/version31.1.3/bitcoinsilver-31.1.3-x86_64-linux-gnu.tar.gz
ARG BTCS_RELEASE_SHA256=6743ecef53501687574a5f761ddb41dcce960953e0e0b6ef362ab69268767c4c

ENV DEBIAN_FRONTEND=noninteractive \
    BTCS_NETWORK=main

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        libbsd0 \
        libevent-2.1-7 \
        libevent-extra-2.1-7 \
        libevent-pthreads-2.1-7 \
        libgssapi-krb5-2 \
        libmd0 \
        libnorm1 \
        libpgm-5.3-0 \
        libsodium23 \
        libsqlite3-0 \
        libzmq5 \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    curl --fail --location --retry 5 --retry-delay 2 --retry-connrefused \
        --output /tmp/btcs.tar.gz "$BTCS_RELEASE_URL"; \
    echo "$BTCS_RELEASE_SHA256  /tmp/btcs.tar.gz" | sha256sum --check --strict -; \
    tar --extract --gzip --file /tmp/btcs.tar.gz --directory /tmp; \
    install --mode 0755 "/tmp/bitcoinsilver-${BTCS_VERSION}/bin/bitcoinsilverd" /usr/local/bin/bitcoinsilverd; \
    install --mode 0755 "/tmp/bitcoinsilver-${BTCS_VERSION}/bin/bitcoinsilver-cli" /usr/local/bin/bitcoinsilver-cli; \
    rm -rf /tmp/btcs.tar.gz "/tmp/bitcoinsilver-${BTCS_VERSION}"; \
    bitcoinsilverd --version

RUN groupadd --system --gid 10001 silverpool \
    && useradd --system --uid 10001 --gid silverpool --home-dir /nonexistent --shell /usr/sbin/nologin silverpool \
    && mkdir -p /data \
    && chown -R silverpool:silverpool /data

COPY deploy/node/entrypoint.sh /usr/local/bin/btcs-node-entrypoint
COPY deploy/node/healthcheck.sh /usr/local/bin/btcs-node-healthcheck
RUN chmod 0755 /usr/local/bin/btcs-node-entrypoint /usr/local/bin/btcs-node-healthcheck

USER 10001:10001

VOLUME ["/data"]
EXPOSE 10566

ENTRYPOINT ["/usr/local/bin/btcs-node-entrypoint"]
