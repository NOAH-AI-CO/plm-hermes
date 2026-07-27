FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv

FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

LABEL maintainer="nesquena"
LABEL description="Hermes Web UI — browser interface for Hermes Agent"

# The customer-facing image does not expose workspace Git, Git remotes, or SSH
# terminal workflows. Build with INSTALL_WORKSPACE_GIT=1 only for an operator
# image that needs those capabilities.
ARG INSTALL_WORKSPACE_GIT=0
ENV HERMES_WEBUI_WORKSPACE_GIT_ENABLED=${INSTALL_WORKSPACE_GIT}

# Install system packages
ENV DEBIAN_FRONTEND=noninteractive

# Make use of apt-cacher-ng if available
RUN if [ "A${BUILD_APT_PROXY:-}" != "A" ]; then \
        echo "Using APT proxy: ${BUILD_APT_PROXY}"; \
        printf 'Acquire::http::Proxy "%s";\n' "$BUILD_APT_PROXY" > /etc/apt/apt.conf.d/01proxy; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN apt-get update -y --fix-missing --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    rsync \
    && if [ "$INSTALL_WORKSPACE_GIT" = "1" ]; then \
        apt-get install -y --no-install-recommends git openssh-client; \
    fi \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Optional GPU user-space acceleration libraries for users who pass through
# host GPU devices. The default image remains CPU-only.
ARG INSTALL_GPU_LIBS=0
RUN if [ "$INSTALL_GPU_LIBS" = "1" ]; then \
        apt-get update -y --fix-missing --no-install-recommends \
        && apt-get install -y --no-install-recommends \
            libva2 \
            vainfo \
            mesa-va-drivers \
        && if apt-cache show intel-media-va-driver-non-free >/dev/null 2>&1; then \
            apt-get install -y --no-install-recommends intel-media-va-driver-non-free; \
        else \
            echo "intel-media-va-driver-non-free is not available from the configured Debian repositories; skipping Intel non-free VA-API driver."; \
        fi \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping optional GPU user-space acceleration libraries (INSTALL_GPU_LIBS=0)."; \
    fi

# Debian slim includes the C.UTF-8 locale, which is sufficient for Python and
# the WebUI's UTF-8 HTTP/JSON handling without generating full locale data.
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /apptoo

# Create the unprivileged runtime user. The entrypoint starts as root only for
# UID/GID alignment and filesystem preparation, then execs the server as this user.
RUN groupadd -g 1024 hermeswebui \
    && useradd -u 1024 -d /home/hermeswebui -g hermeswebui -G users -s /bin/bash -m hermeswebui \
    && mkdir -p /app /uv_cache /workspace \
    && chown -R hermeswebui:hermeswebui /home/hermeswebui /app /uv_cache /workspace \
    && chmod 0755 /home/hermeswebui \
    && chmod 1777 /app /uv_cache /workspace

COPY --chmod=555 docker_init.bash /hermeswebui_init.bash

RUN touch /.within_container

# Remove APT proxy configuration and clean up APT downloaded files
RUN rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/01proxy \
    && apt-get clean

USER root

# Pre-install uv system-wide so the container doesn't need internet access at runtime.
# Copying the pinned official binary image avoids shipping curl in the runtime.
# The init script will skip the download when uv is already on PATH.
COPY --from=uv /uv /uvx /usr/local/bin/

COPY --chown=root:root . /apptoo

# Bake the git version tag into the image so the settings badge works even
# when .git is not present (it is excluded by .dockerignore).
# CI passes: --build-arg HERMES_VERSION=$(git describe --tags --always)
# Local builds that omit the arg get "unknown" as the fallback.
ARG HERMES_VERSION=unknown
RUN echo "__version__ = '${HERMES_VERSION}'" > /apptoo/api/_version.py

# Default to binding all interfaces (required for container networking)
ENV HERMES_WEBUI_HOST=0.0.0.0
ENV HERMES_WEBUI_PORT=8787

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=8s --start-period=10s --retries=3 \
  CMD bash /apptoo/scripts/lib/health_probe.sh localhost 8787 /health 2 >/dev/null || exit 1

# docker_init.bash performs root-only bind-mount setup, then drops to hermeswebui
# before starting the WebUI server. The production image does not ship sudo.
USER root
CMD ["/hermeswebui_init.bash"]

