#!/bin/bash
###############################################################################
# Start Backend Services (Letter Model + Word Resolver)
# Runs until Ctrl+C is pressed
###############################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
WS_URL="wss://opcs2s86c2.execute-api.us-east-1.amazonaws.com/dev"
STREAM_NAME="asl-letters-stream"
REGION="us-east-1"
SESSION_ID="AWS-REPLAY-TEST"
LOG_FILE="/tmp/word-resolver-test-$(date +%Y%m%d-%H%M%S).log"
LETTER_MODEL_LOG="/tmp/letter-model-test-$(date +%Y%m%d-%H%M%S).log"

# PID tracking
CONSUMER_PID=""
LETTER_MODEL_PID=""

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}[CLEANUP] Stopping services...${NC}"
    
    if [ -n "$CONSUMER_PID" ]; then
        kill $CONSUMER_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Stopped word-resolver (PID: $CONSUMER_PID)${NC}"
    fi
    
    if [ -n "$LETTER_MODEL_PID" ]; then
        kill $LETTER_MODEL_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Stopped letter-model (PID: $LETTER_MODEL_PID)${NC}"
    fi
    
    # Kill any remaining processes
    pkill -f "python.*word-resolver.*main.py" 2>/dev/null || true
    pkill -f "python.*letter-model.*main.py" 2>/dev/null || true
    
    echo -e "${GREEN}✓ Cleanup complete${NC}"
}

# Set trap for cleanup on exit
trap cleanup EXIT INT TERM

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Starting Backend Services${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Stop existing services
echo -e "${YELLOW}[1/3] Stopping existing services...${NC}"
pkill -f "python.*word-resolver.*main.py" 2>/dev/null || true
pkill -f "python.*letter-model.*main.py" 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Services stopped${NC}"
echo ""

# Step 3: Start letter-model service
echo -e "${YELLOW}[2/3] Starting letter-model service...${NC}"
cd /src/letter-model-service/
nohup uv run python main.py > "$LETTER_MODEL_LOG" 2>&1 &
LETTER_MODEL_PID=$!
echo -e "${GREEN}✓ Letter-model started (PID: $LETTER_MODEL_PID)${NC}"
echo ""

# Step 4: Start word-resolver service
echo -e "${YELLOW}[3/3] Starting word-resolver service...${NC}"
cd /src/word-resolver-service/
nohup uv run python main.py > "$LOG_FILE" 2>&1 &
CONSUMER_PID=$!
echo -e "${GREEN}✓ Word-resolver started (PID: $CONSUMER_PID)${NC}"

# Wait for services to be ready
echo -e "${YELLOW}Waiting for services to initialize (letter-model takes ~45s for TensorFlow)...${NC}"
sleep 50

# Check if word-resolver is running and consuming
echo -e "${YELLOW}Checking if word-resolver is consuming from Kinesis...${NC}"
for i in {1..20}; do
    if grep -q "Consuming from shard" "$LOG_FILE" 2>/dev/null; then
        echo -e "${GREEN}✓ Word-resolver is consuming from Kinesis${NC}"
        break
    fi
    if [ $i -eq 20 ]; then
        echo -e "${RED}⚠ Word-resolver may not be ready${NC}"
    fi
    sleep 2
done

# Check if letter-model is running
if grep -q "EFO subscription active" "$LETTER_MODEL_LOG" 2>/dev/null; then
    echo -e "${GREEN}✓ Letter-model is processing landmarks${NC}"
else
    echo -e "${YELLOW}⚠ Checking letter-model status...${NC}"
    sleep 5
fi
echo ""

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Services Running${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Letter-model PID: $LETTER_MODEL_PID${NC}"
echo -e "${GREEN}Word-resolver PID: $CONSUMER_PID${NC}"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo -e "  Letter-model: tail -f $LETTER_MODEL_LOG"
echo -e "  Word-resolver: tail -f $LOG_FILE"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Keep running until Ctrl+C
while true; do
    # Check if processes are still running
    if ! kill -0 $LETTER_MODEL_PID 2>/dev/null; then
        echo -e "${RED}✗ Letter-model process died unexpectedly${NC}"
        break
    fi
    
    if ! kill -0 $CONSUMER_PID 2>/dev/null; then
        echo -e "${RED}✗ Word-resolver process died unexpectedly${NC}"
        break
    fi
    
    sleep 5
done
