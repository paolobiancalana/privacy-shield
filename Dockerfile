# privacy-shield/Dockerfile
FROM python:3.12-slim

# Security: run as non-root
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/sh --create-home appuser

WORKDIR /app

# Install dependencies before copying source (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Drop root privileges
USER appuser

EXPOSE 8000

# Uvicorn with 1 worker (scale via horizontal pod replication, not threads)
# workers=1 ensures AsyncLocalStorage (if added later) is process-scoped
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
