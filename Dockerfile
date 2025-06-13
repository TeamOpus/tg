# Build stage
FROM python:3.9-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Runtime stage
FROM python:3.9-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus0 \
    libssl1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app

# Ensure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Create necessary directories
RUN mkdir -p /app/downloads /app/logs /app/temp

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    LOG_FILE=/app/logs/bot.log \
    TEMP_DIR=/app/temp \
    DOWNLOADS_DIR=/app/downloads

# Volumes for persistent data
VOLUME ["/app/downloads", "/app/logs", "/app/temp"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Entrypoint
ENTRYPOINT ["python", "main.py"]

