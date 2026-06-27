# Production image for the Fleet Watch Pro FastAPI backend.
FROM python:3.12-slim

# Faster, quieter, no .pyc clutter; unbuffered logs for container log drivers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for asyncpg/bcrypt wheels; kept minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so the layer caches across app-code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# App code + migrations.
COPY . .

# Run as a non-root user. Pre-create the uploads dir owned by appuser so a fresh
# named volume mounted at /data/uploads inherits writable ownership.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Apply migrations, then start the server. Bind to 0.0.0.0 and respect the
# platform-provided $PORT (Railway/Render set it); default to 8000 locally.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
