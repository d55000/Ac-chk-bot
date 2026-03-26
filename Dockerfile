# ── Build stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create a non-root user for security.
RUN groupadd --gid 1000 botuser && \
    useradd --uid 1000 --gid botuser --create-home botuser

WORKDIR /app

# Install dependencies first (layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

# Create the data directory (for the SQLite DB and temp files).
RUN mkdir -p /app/data && chown -R botuser:botuser /app

# Switch to non-root user.
USER botuser

# Declare the volume for persistent data (SQLite DB).
VOLUME ["/app/data"]

ENTRYPOINT ["python", "main.py"]
