# --- Stage 1: builder (internet required - fetches every uv dependency) ---
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Whole workspace: gui/ depends on the daq-core submodule and utils/ as uv
# workspace members, all pinned by the single root uv.lock.
COPY . .

# --all-packages: a plain `uv sync` here would only install the workspace
# root's own trivial dependency (msgpack) - gui/python-api's actual deps
# only get pulled in by explicitly syncing every workspace member.
# --no-editable: installs them as regular packages rather than path
# references, so the runtime stage below only needs the resulting .venv/ -
# not this stage's source checkout state.
RUN uv sync --frozen --no-dev --no-editable --all-packages

# --- Stage 2: runtime (fully offline - no uv, no network access needed) ---
FROM python:3.12-slim-trixie

WORKDIR /app/gui

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV=/app/.venv

# gui/config.py's data/log paths are relative to the CWD, matching
# `cd gui && uv run main.py` - WORKDIR above must stay gui/, not /app.
EXPOSE 8080

CMD ["python", "main.py"]
