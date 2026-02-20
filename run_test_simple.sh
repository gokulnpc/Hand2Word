#!/bin/bash
###############################################################################
# Word Resolver AWS Test - Clean run with proper setup and teardown
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
echo -e "${BLUE}Word Resolver AWS Test${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Stop existing services
echo -e "${YELLOW}[1/7] Stopping existing services...${NC}"
pkill -f "python.*word-resolver.*main.py" 2>/dev/null || true
pkill -f "python.*letter-model.*main.py" 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Services stopped${NC}"
echo ""

# Step 2: Flush Redis data for session
echo -e "${YELLOW}[2/7] Flushing Redis data for session: $SESSION_ID${NC}"
redis-cli DEL "word:$SESSION_ID" > /dev/null 2>&1 || true
redis-cli DEL "window:$SESSION_ID" > /dev/null 2>&1 || true
redis-cli DEL "commit:$SESSION_ID" > /dev/null 2>&1 || true
echo -e "${GREEN}✓ Redis data flushed${NC}"
echo ""

# Step 3: Start letter-model service
echo -e "${YELLOW}[3/7] Starting letter-model service...${NC}"
cd /src/letter-model-service/
nohup uv run python main.py > "$LETTER_MODEL_LOG" 2>&1 &
LETTER_MODEL_PID=$!
echo -e "${GREEN}✓ Letter-model started (PID: $LETTER_MODEL_PID)${NC}"
echo ""

# Step 4: Start word-resolver service
echo -e "${YELLOW}[4/7] Starting word-resolver service...${NC}"
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

# Step 6: Run AWS replay test
echo -e "${YELLOW}[6/7] Running AWS replay test...${NC}"
python3 test_replay_AWS.py "$WS_URL" test_data_AWS.json
echo ""

# Step 7: The test_replay_AWS.py now waits 10 seconds internally for responses
# We don't need to wait here anymore since the script handles it

# Step 7: Check results
echo -e "${YELLOW}[7/7] Checking results${NC}"
echo ""

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Redis State${NC}"
echo -e "${BLUE}========================================${NC}"

# Check all session-related keys
echo -e "${YELLOW}All keys in Redis:${NC}"
redis-cli KEYS "*" 2>/dev/null || echo "(none)"
echo ""

echo -e "${YELLOW}Session-specific keys for: $SESSION_ID${NC}"
redis-cli KEYS "*$SESSION_ID*" 2>/dev/null || echo "(none)"
echo ""

# Word buffer
WORD_BUFFER=$(redis-cli GET "word:$SESSION_ID" 2>/dev/null || echo "")
if [ -n "$WORD_BUFFER" ]; then
    WORD=$(echo "$WORD_BUFFER" | jq -r '.letters | join("")' 2>/dev/null || echo "ERROR")
    echo -e "${GREEN}Word buffer (word:$SESSION_ID):${NC}"
    echo "$WORD_BUFFER" | jq '.' 2>/dev/null || echo "$WORD_BUFFER"
    echo -e "  → Resolved word: ${GREEN}$WORD${NC}"
else
    echo -e "${YELLOW}Word buffer (word:$SESSION_ID): (empty or cleared)${NC}"
fi
echo ""

# Sliding window
WINDOW_SIZE=$(redis-cli LLEN "window:$SESSION_ID" 2>/dev/null || echo "0")
echo -e "${GREEN}Sliding window (window:$SESSION_ID): $WINDOW_SIZE entries${NC}"
if [ "$WINDOW_SIZE" -gt 0 ]; then
    echo -e "${YELLOW}Sample entries:${NC}"
    redis-cli LRANGE "window:$SESSION_ID" 0 4 2>/dev/null | while read -r entry; do
        if [ -n "$entry" ]; then
            CHAR=$(echo "$entry" | jq -r '.char' 2>/dev/null || echo "?")
            CONF=$(echo "$entry" | jq -r '.confidence' 2>/dev/null || echo "?")
            echo "  - '$CHAR' (conf: $CONF)"
        fi
    done
fi
echo ""

# Last commit
LAST_COMMIT=$(redis-cli GET "commit:$SESSION_ID" 2>/dev/null || echo "")
if [ -n "$LAST_COMMIT" ]; then
    echo -e "${GREEN}Last commit (commit:$SESSION_ID):${NC}"
    echo "$LAST_COMMIT" | jq '.' 2>/dev/null || echo "$LAST_COMMIT"
else
    echo -e "${YELLOW}Last commit (commit:$SESSION_ID): (none)${NC}"
fi
echo ""

echo -e "${BLUE}Recent Activity Logs:${NC}"
cat $LOG_FILE | grep -E "(Committed|Pause|Finalized|Resolved|Top 5 results)" | tail -20

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Configuration:${NC}"
echo "  • window_duration_ms: 300ms"
echo "  • stability_duration_ms: 200ms"
echo "  • max_consecutive_same: 2 letters (removed dedupe_threshold_ms)"
echo "  • pause_duration_ms: 2000ms"
echo ""
echo ""
echo -e "${BLUE}Logs:${NC}"
echo "  • Word-resolver: $LOG_FILE"
echo "  • Letter-model: $LETTER_MODEL_LOG"
echo -e "${BLUE}========================================${NC}"

