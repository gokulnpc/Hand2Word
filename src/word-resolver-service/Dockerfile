# Word Resolver Service - Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1

# Environment variables for AWS and services
ENV AWS_REGION="us-east-1" \
    LETTERS_STREAM_NAME="asl-letters-stream" \
    REDIS_HOST="localhost" \
    REDIS_PORT="6379"

# Create working directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY uv.lock pyproject.toml ./

# Install uv using pip
RUN pip install --no-cache-dir uv
RUN uv sync --locked

# Verify Python is available
RUN python3 --version

# Copy application code
COPY ./services ./services
COPY ./models.py ./models.py
COPY ./config.py ./config.py
COPY ./main.py ./main.py

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Run the service
CMD ["python3", "main.py"]

