# One image, two runtimes: the Windows box on draft night and the cluster as a warm spare.
# audible performs no platform writes, so both can run at once without conflicting -- that is
# what makes failover a matter of opening a different URL.

FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, from the lockfile only, so a source edit does not re-resolve or
# re-download polars on every build. README.md rides along because pyproject declares
# `readme = "README.md"` and hatchling reads it when the project itself is installed below --
# without it the second sync fails on a file that has nothing to do with the build.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --extra nflverse

COPY src/ ./src/
COPY leagues/ ./leagues/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra nflverse


FROM python:3.12-slim-bookworm AS runtime

# No uv, no compilers, no build cache in the final layer -- only the venv and the source.
RUN useradd --create-home --uid 10001 audible
WORKDIR /app

COPY --from=build --chown=audible:audible /app/.venv /app/.venv
COPY --from=build --chown=audible:audible /app/src /app/src
COPY --from=build --chown=audible:audible /app/leagues /app/leagues

# The league configs are read relative to the package root (loader.py walks up three parents),
# so the layout above must mirror the repo. data/cache holds the board cache and draft state.
RUN mkdir -p /app/data/cache && chown -R audible:audible /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER audible
EXPOSE 8080

# 0.0.0.0 so the port is reachable from outside the container; --league is baked because this
# image serves one cockpit at a time and the alternative is remembering a flag at 8pm.
CMD ["audible", "serve", "--league", "sleeper_boyfun", "--host", "0.0.0.0", "--port", "8080"]
