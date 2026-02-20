#!/bin/bash
###############################################################################
# Test Word Resolver Docker Locally
# This script builds and runs the word-resolver Docker container locally
# with MongoDB and Redis configuration from .env
###############################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Word Resolver Docker Local Test${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Check prerequisites
echo -e "${YELLOW}[1/5] Checking prerequisites...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found. Please install Docker.${NC}"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo -e "${RED}✗ .env file not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker found${NC}"
echo -e "${GREEN}✓ .env file found${NC}"
echo ""

# Step 2: Check Redis is running
echo -e "${YELLOW}[2/5] Checking Redis connection...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis is running${NC}"
else
    echo -e "${RED}✗ Redis is not running. Starting Redis...${NC}"
    echo -e "${YELLOW}Please start Redis first: redis-server${NC}"
    exit 1
fi
echo ""

# Step 3: Build Docker image
echo -e "${YELLOW}[3/5] Building Docker image...${NC}"
docker build -t word-resolver-service:local .
echo -e "${GREEN}✓ Docker image built${NC}"
echo ""

# Step 4: Stop existing container
echo -e "${YELLOW}[4/5] Stopping existing container (if any)...${NC}"
docker stop word-resolver-local 2>/dev/null || true
docker rm word-resolver-local 2>/dev/null || true
echo -e "${GREEN}✓ Cleaned up${NC}"
echo ""

# Step 5: Run container with .env
echo -e "${YELLOW}[5/5] Starting Word Resolver container...${NC}"
echo -e "${YELLOW}Container name: word-resolver-local${NC}"
echo ""

# For Linux/WSL2: use host.docker.internal for Redis on host
# For Mac: use host.docker.internal automatically
docker run -d \
  --name word-resolver-local \
  --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  -e REDIS_HOST=host.docker.internal \
  -e AWS_PROFILE=AdministratorAccess-837563944845 \
  -v ~/.aws:/home/appuser/.aws:ro \
  word-resolver-service:local

echo -e "${GREEN}✓ Container started${NC}"
echo ""

# Wait for initialization
echo -e "${YELLOW}Waiting for service to initialize...${NC}"
sleep 10

# Check logs
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Container Logs (last 30 lines)${NC}"
echo -e "${BLUE}========================================${NC}"
docker logs --tail 30 word-resolver-local

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Service Status${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Word Resolver running in Docker${NC}"
echo ""
echo -e "${YELLOW}Commands:${NC}"
echo -e "  • View logs:    docker logs -f word-resolver-local"
echo -e "  • Stop service: docker stop word-resolver-local"
echo -e "  • Remove:       docker rm word-resolver-local"
echo ""
echo -e "${YELLOW}Now you can run: python3 ../../test_replay_AWS.py <ws_url> ../../test_data_AWS.json${NC}"
echo -e "${BLUE}========================================${NC}"
