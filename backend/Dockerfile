# AdFlow AI — production backend image.
#
# Two things make this image different from a generic Python one, and both are
# load-bearing for the product:
#
#   * FFmpeg — photo motion, remixing, assembly, export and QC all shell out to
#     it. No FFmpeg means no deliverable.
#   * Arabic fonts — captions are rasterised by us. A machine without an
#     Arabic-capable font renders empty boxes, so the fonts ship in the image
#     rather than being assumed.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LOG_FORMAT=json

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-noto-core \
        fonts-noto-cjk \
        fonts-dejavu-core \
        fontconfig \
        curl \
        libraqm0 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# The brand faces. Noto Kufi (from fonts-noto-core above) is the fallback and
# is perfectly readable, but Cairo and Tajawal are what the captions are
# designed around — a display face with real weight over a photograph. Fetched
# rather than apt-installed because Debian ships neither.
#
# `|| true`: a build behind a restrictive egress policy must still produce a
# working image. captions.py walks this list and falls through to Kufi, so a
# missing font changes the look, never the behaviour.
ARG GOOGLE_FONTS_RAW=https://github.com/google/fonts/raw/main/ofl
RUN mkdir -p /usr/share/fonts/truetype/adflow \
    && (curl -fsSL --retry 2 --max-time 45 -o /tmp/cairo.ttf \
          "${GOOGLE_FONTS_RAW}/cairo/Cairo%5Bslnt%2Cwght%5D.ttf" \
        && cp /tmp/cairo.ttf /usr/share/fonts/truetype/adflow/Cairo-Bold.ttf || true) \
    && (curl -fsSL --retry 2 --max-time 45 -o /usr/share/fonts/truetype/adflow/Tajawal-Bold.ttf \
          "${GOOGLE_FONTS_RAW}/tajawal/Tajawal-Bold.ttf" || true) \
    && find /usr/share/fonts/truetype/adflow -size -1k -delete \
    && fc-cache -f \
    && fc-list :lang=ar family | sort -u

WORKDIR /app

# Dependencies first so application edits do not invalidate the wheel cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user: this process shells out to FFmpeg on customer-supplied
# media, which is exactly the kind of surface that should not be root.
RUN useradd --create-home --uid 10001 adflow \
    && mkdir -p /app/storage \
    && chown -R adflow:adflow /app
USER adflow

EXPOSE 8000

# Liveness only. Orchestrators should additionally gate traffic on /ready,
# which verifies the database, storage, queue and FFmpeg.
HEALTHCHECK --interval=20s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations are NOT run here — a web instance that migrates on boot will race
# every other instance in a rolling deploy. Run them as a release step:
#   docker run --rm <image> alembic upgrade head
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "2"]
