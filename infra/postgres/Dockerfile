# PostgreSQL 17 + PostGIS 3 + pgvector, multi-arch (amd64 + arm64).
#
# The upstream postgis/postgis image has historically shipped amd64 only, which
# runs under emulation on Apple Silicon and on a Raspberry Pi. Building on the
# official postgres image and pulling extensions from the PGDG apt repository it
# already trusts gives native images on both architectures with no third party.
FROM postgres:17-bookworm

# PG_MAJOR is set by the base image, so the extension packages always match the
# server version the image actually ships.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      "postgresql-${PG_MAJOR}-postgis-3" \
      "postgresql-${PG_MAJOR}-postgis-3-scripts" \
      "postgresql-${PG_MAJOR}-pgvector" \
 && rm -rf /var/lib/apt/lists/*

COPY initdb/ /docker-entrypoint-initdb.d/

HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=10 \
  CMD ["sh", "-c", "pg_isready -U \"${POSTGRES_USER:-postgres}\" -d \"${POSTGRES_DB:-postgres}\""]
