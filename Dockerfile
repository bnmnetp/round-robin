FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 1000 rr && mkdir /data && chown rr /data
USER rr

ENV PATH="/app/.venv/bin:$PATH" \
    RR_DATABASE_URL=sqlite:////data/rr.db
VOLUME /data
EXPOSE 8000

# One worker: SQLite wants a single writer, and one process is plenty for a club.
# --proxy-headers so the share link and QR code use the public https URL.
CMD ["uvicorn", "--factory", "rr.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
