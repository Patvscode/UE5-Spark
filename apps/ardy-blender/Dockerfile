# syntax=docker/dockerfile:1.7
#
# Real distro Blender, not a custom renderer. The Ubuntu base digest and the
# Blender/blender-data packages are deliberately pinned for reproducibility.
FROM ubuntu:26.04@sha256:3131b4cc82a783df6c9df078f86e01819a13594b865c2cad47bd1bca2b7063bb

ARG DEBIAN_FRONTEND=noninteractive
ARG BLENDER_VERSION=5.0.1+dfsg-1ubuntu1
ARG BLENDER_DATA_VERSION=5.0.1+dfsg-1ubuntu1
ARG APP_UID=1000
ARG APP_GID=1000

LABEL io.ue5-spark.blender.version="5.0.1"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       "blender=${BLENDER_VERSION}" \
       "blender-data=${BLENDER_DATA_VERSION}" \
       ca-certificates \
       libgl1 \
       libx11-6 \
       libxext6 \
       libxi6 \
       libxkbcommon-x11-0 \
       libxrender1 \
       python3-numpy \
    && rm -rf /var/lib/apt/lists/*

RUN if ! getent group "${APP_GID}" >/dev/null; then \
        groupadd --gid "${APP_GID}" blender; \
    fi \
    && if ! getent passwd "${APP_UID}" >/dev/null; then \
        useradd --uid "${APP_UID}" --gid "${APP_GID}" \
          --create-home --home-dir /var/lib/ardy-blender \
          --shell /usr/sbin/nologin blender; \
    fi \
    && install -d -o "${APP_UID}" -g "${APP_GID}" /var/lib/ardy-blender

COPY --chown=${APP_UID}:${APP_GID} ardy_blender /opt/ue5-spark/ardy_blender

USER ${APP_UID}:${APP_GID}
WORKDIR /workspace

ENV HOME=/var/lib/ardy-blender \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=graphics,display,utility,compute

ENTRYPOINT ["blender"]
