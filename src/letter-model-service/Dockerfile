FROM python:3.12-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Set environment variables
# PATH is used to set the path to the virtual environment
# PYTHONUNBUFFERED is used to prevent buffering of output
# PYTHONDONTWRITEBYTECODE is used to prevent writing bytecode to the disk
# UV_COMPILE_BYTECODE is used to compile bytecode to the disk
ENV PATH="/app/.venv/bin:$PATH" \ 
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1\
    UV_COMPILE_BYTECODE=1

# Environment variables for AWS Kinesis streams
ENV LANDMARKS_STREAM_NAME="asl-landmarks-stream" \
    LETTERS_STREAM_NAME="asl-letters-stream" \
    AWS_REGION="us-east-1" \
    POLLING_INTERVAL="1"

# Create a folder /app if it doesn't exist,
# the /app folder is the current working directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY uv.lock pyproject.toml ./

# Install uv using pipx
RUN pip install --no-cache-dir uv
RUN uv sync --locked

# Verify Python is available
RUN python3 --version

# Copy necessary files to our app
COPY ./services ./services
COPY ./utils ./utils
COPY ./constant ./constant
COPY ./model ./model
COPY ./main.py ./main.py

# Run as non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Run the Kinesis consumer/producer service
CMD ["python3", "main.py"]
