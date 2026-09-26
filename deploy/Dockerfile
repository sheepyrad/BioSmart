# One image from the same pixi.lock as `pixi install --locked --frozen`.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIXI_HOME=/usr/local/pixi \
    PIXI_NO_PATH_UPDATE=1 \
    PATH=/usr/local/pixi/bin:${PATH}

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl bzip2 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://pixi.sh/install.sh | bash \
    && ln -sfn /usr/local/pixi/bin/pixi /usr/local/bin/pixi

WORKDIR /opt/biosmart

# Path packages named by the lockfile. Do not resolve a second lock.
COPY pixi.toml pixi.lock ./
COPY biosmart biosmart
COPY cgflow cgflow

RUN mkdir -p \
        cgflow/weights \
        cgflow/src/FlashBind/checkpoints \
        cgflow/src/FlashBind/FABind_plus/ckpt \
    && pixi install --locked --frozen --all \
    && chmod -R a+rX /opt/biosmart /usr/local/pixi

COPY deploy/entrypoint.sh /usr/local/bin/biosmart-entrypoint
RUN chmod 755 /usr/local/bin/biosmart-entrypoint

ENTRYPOINT ["/usr/local/bin/biosmart-entrypoint"]
