# One image holds both engines and the harness:
#   - msq-runner, the driver around cursor/minisqlite (built from vendor/minisqlite)
#   - a pinned SQLite, compiled from the official amalgamation, which Python's
#     sqlite3 module is made to load instead of the Debian copy
#   - the msqdiff harness
#
# The SQLite release is a build argument because the answer to "is this a bug?"
# depends on the release: minisqlite's own comments cite behaviour from the
# SQLite 3.52/3.53 documentation, and Python's bundled SQLite is older than that.
#   docker build -t msqdiff:3541 .
#   docker build -t msqdiff:3533 --build-arg SQLITE_NUM=3530300 --build-arg SQLITE_SHA3= .
#   docker build -t msqdiff:3500 --build-arg SQLITE_YEAR=2025 --build-arg SQLITE_NUM=3500000 --build-arg SQLITE_SHA3= .
ARG SQLITE_NUM=3540100
ARG SQLITE_YEAR=2026
# SHA3-256 of the amalgamation zip as printed on sqlite.org/download.html for 3.54.1.
# Leave empty to skip the comparison; the computed hash is still printed in the build log.
ARG SQLITE_SHA3=92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30

# minisqlite uses edition 2024, which needs Rust 1.85 or newer; the floating `1` tag
# gives the current stable release.
#
# The minisqlite source is a build argument too, so the same harness can be run against a
# patched checkout:
#   docker build -t msqdiff:patched --build-arg MSQ_SRC=vendor/minisqlite-fixed .
ARG MSQ_SRC=vendor/minisqlite
FROM rust:1-bookworm AS build-runner
ARG MSQ_SRC
WORKDIR /w
COPY runner /w/runner
COPY ${MSQ_SRC} /w/vendor/minisqlite
WORKDIR /w/runner
RUN cargo build --release

FROM python:3.13-slim-bookworm AS build-sqlite
ARG SQLITE_NUM
ARG SQLITE_YEAR
ARG SQLITE_SHA3
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev unzip curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /s
COPY scripts/check_hash.py /s/check_hash.py
RUN curl -fsSLo sqlite.zip "https://www.sqlite.org/${SQLITE_YEAR}/sqlite-amalgamation-${SQLITE_NUM}.zip" \
 && python /s/check_hash.py sqlite.zip "${SQLITE_SHA3}" \
 && unzip -q sqlite.zip \
 && mkdir -p /out \
 && gcc -O2 -fPIC -shared \
      -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_FTS5 \
      -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_DBSTAT_VTAB -DSQLITE_THREADSAFE=1 \
      "sqlite-amalgamation-${SQLITE_NUM}/sqlite3.c" -o /out/libsqlite3.so.0 -lpthread -ldl -lm

FROM python:3.13-slim-bookworm
COPY --from=build-sqlite /out/libsqlite3.so.0 /opt/sqlite/lib/libsqlite3.so.0
ENV LD_LIBRARY_PATH=/opt/sqlite/lib
COPY --from=build-runner /w/runner/target/release/msq-runner /usr/local/bin/msq-runner
ENV MSQ_RUNNER=/usr/local/bin/msq-runner
WORKDIR /app
COPY msqdiff /app/msqdiff
COPY findings /app/findings
COPY tests /app/tests
ENTRYPOINT ["python", "-X", "utf8", "-B", "-m", "msqdiff"]
