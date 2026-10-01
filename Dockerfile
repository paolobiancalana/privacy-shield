# privacy-shield/Dockerfile
FROM python:3.12-slim

# Security: run as non-root
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/sh --create-home appuser

WORKDIR /app

# Install dependencies before copying source (better layer caching)
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

# Create model directory with correct permissions
RUN mkdir -p /opt/pii/model && chown -R appuser:appgroup /opt/pii

# Copy application source
COPY app/ ./app/

# Copy model from host (assumes it exists in .local/pii-model)
COPY --chown=appuser:appgroup .local/pii-model /opt/pii/model

# Drop root privileges
USER appuser

EXPOSE 8000

# Uvicorn with 1 worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
