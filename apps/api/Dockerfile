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

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# --- Runtime -----------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Runtime spatial libraries (no compilers).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    libgeos-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user.
RUN groupadd --system satrak && useradd --system --gid satrak --create-home satrak

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=satrak:satrak alembic.ini ./
COPY --chown=satrak:satrak alembic ./alembic
COPY --chown=satrak:satrak app ./app

USER satrak
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
