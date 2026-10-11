# syntax=docker/dockerfile:1
# =============================================================================
# SATRAK API — multi-stage image
# =============================================================================
# Stage 1 (builder) installs dependencies into a virtualenv; stage 2 (runtime)
# copies only that venv + source onto a slim base, so the final image carries no
# build toolchain. GDAL/GEOS system libs are included for GeoAlchemy2/Shapely.
# -----------------------------------------------------------------------------

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md requirements.lock ./
RUN pip install --upgrade pip && pip install --require-hashes -r requirements.lock
COPY app ./app
RUN pip install --no-deps .
# The runtime never installs packages. pip bundles its own copies of urllib3/msgpack that
# Trivy reports separately from the locked dependencies, so drop pip from the venv before it
# is copied into the runtime stage (the console scripts uvicorn/alembic do not need it).
RUN pip uninstall -y pip && ! python -c "import pip" 2>/dev/null

# --- Runtime -----------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# No system packages are installed in this stage on purpose. The locked runtime dependencies
# contain no GDAL/GEOS binding (GeoAlchemy2 needs only SQLAlchemy) and the application imports
# none, so development packages such as libgdal-dev only added attack surface. A future raster
# adapter that needs native libraries must declare and install its own runtime packages (not -dev
# packages) in its own change, with its own image scan.

# The base image ships pip, setuptools and wheel in the system site-packages. Nothing at runtime
# needs them (none of the locked runtime packages requires setuptools or wheel, and app/ has no
# pkg_resources/setuptools import), so remove them; the check fails the build if any survive.
RUN /usr/local/bin/python -m pip uninstall -y pip setuptools wheel \
    && ! /usr/local/bin/python -c "import importlib.util as u, sys; sys.exit(0 if any(u.find_spec(m) for m in ('pip','setuptools','pkg_resources','wheel')) else 1)"

# Run as a non-root user.
RUN groupadd --system satrak && useradd --system --gid satrak --create-home satrak

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=satrak:satrak alembic.ini ./
COPY --chown=satrak:satrak alembic ./alembic
COPY --chown=satrak:satrak app ./app
COPY --chown=satrak:satrak healthcheck.py ./

USER satrak
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

# --no-proxy-headers: uvicorn must not rewrite client addresses from X-Forwarded-For; the
# application resolves them (rate_limit.trusted_proxy_*) so there is exactly one trust path.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
