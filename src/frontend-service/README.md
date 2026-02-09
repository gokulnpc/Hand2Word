# ASL Frontend Service - MediaPipe Holistic Client

Real-time ASL (American Sign Language) recognition frontend that captures holistic body landmarks using MediaPipe and streams them to the backend via WebSocket + Kinesis.

## Overview

This service runs on the client side (user's computer with a webcam) and:
- Captures video from webcam
- Processes frames with **MediaPipe Holistic** to extract:
  - Face landmarks (468 points)
  - Pose landmarks (33 points)
  - Left hand landmarks (21 points)
  - Right hand landmarks (21 points)
- Sends 1662-value flattened arrays to Kinesis via WebSocket API Gateway
- Displays real-time visualization with FPS counter

## Architecture

```
Webcam → MediaPipe Holistic → extract_keypoints() → WebSocket → API Gateway → Kinesis
   ↓                                                                              ↓
OpenCV Display (pose + hands visualization)                           Letter Model Service
```

## Data Format

The `extract_keypoints()` function produces a **1662-value array** in this order:

```python
# Order: pose → face → left_hand → right_hand
[
    pose:       33 × 4 = 132 values  (x, y, z, visibility)
    face:      468 × 3 = 1404 values (x, y, z)
    left_hand:  21 × 3 = 63 values   (x, y, z)
    right_hand: 21 × 3 = 63 values   (x, y, z)
]
Total: 1662 values
```

This matches the backend's expected format in `letter-model-service`.

## Installation

Using `uv` (recommended):

```bash
cd src/frontend-service

# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
```

## Usage

### Basic Usage (with default WebSocket URL)

```bash
cd src/frontend-service
source .venv/bin/activate

python app.py
```

The default WebSocket URL is: `wss://el9vhr7tx1.execute-api.us-east-1.amazonaws.com/dev`

### Custom WebSocket URL

```bash
python app.py --kinesis_ws_url wss://YOUR_API_GATEWAY_URL.execute-api.us-east-1.amazonaws.com/dev
```

### All Options

```bash
python app.py \
  --device 0 \
  --width 960 \
  --height 540 \
  --kinesis_ws_url wss://YOUR_URL/dev \
  --session_id my-session-123 \
  --min_detection_confidence 0.5 \
  --min_tracking_confidence 0.5
```

**Arguments:**
- `--device`: Camera device ID (default: 0)
- `--width`: Video width (default: 960)
- `--height`: Video height (default: 540)
- `--kinesis_ws_url`: WebSocket API Gateway URL
- `--session_id`: Custom session ID (default: auto-generated)
- `--min_detection_confidence`: MediaPipe detection confidence (default: 0.5)
- `--min_tracking_confidence`: MediaPipe tracking confidence (default: 0.5)

## Controls

- **ESC**: Exit the application
- The window displays:
  - Real-time pose skeleton
  - Left and right hand landmarks
  - FPS counter

## WebSocket Protocol

### Send Message (Client → API Gateway)

```json
{
  "action": "sendlandmarks",
  "session_id": "session_12345",
  "data": [/* 1662 float values */]
}
```

### Backend Flow

```
app.py → API Gateway → Lambda → Kinesis (asl-landmarks-stream)
                                    ↓
                          Letter Model Service (EFO consumer)
                                    ↓
                          Kinesis (asl-letters-stream)
```

## Dependencies

- **mediapipe** (0.10.21+): Holistic landmark detection
- **opencv-python** (4.11.0+): Video capture and display
- **websockets** (15.0.1+): WebSocket client
- **numpy** (1.26.4+): Array operations

All managed via `pyproject.toml` and `uv.lock`.

## File Structure

```
frontend-service/
├── app.py              # Main application (MediaPipe Holistic + WebSocket)
├── utils/
│   ├── __init__.py
│   └── cvfpscalc.py    # FPS calculation utility
├── pyproject.toml      # UV project dependencies
├── uv.lock             # Locked dependencies
└── README.md           # This file
```

## Troubleshooting

### Camera Not Found
```bash
# List available cameras
python -c "import cv2; print([i for i in range(10) if cv2.VideoCapture(i).read()[0]])"

# Use specific camera
python app.py --device 1
```

### WebSocket Connection Issues
- Verify the API Gateway URL is correct
- Check AWS credentials (if using authenticated endpoints)
- Ensure Kinesis stream `asl-landmarks-stream` exists

### Low FPS
- Reduce video resolution: `--width 640 --height 480`
- Disable face mesh drawing (already commented out in code)
- Use `model_complexity=0` in `app.py` (currently set to 1)

## Development Notes

### Switching from MediaPipe Hands to Holistic

This service was migrated from MediaPipe Hands to MediaPipe Holistic to support:
1. **Multi-hand detection** filtering (both hands → skip inference for fingerspelling)
2. **Handedness detection** (left vs right hand)
3. **Body context** for future ASL word-level recognition

### MediaPipe Holistic Configuration

```python
holistic = mp_holistic.Holistic(
    static_image_mode=False,        # Video mode (faster)
    model_complexity=1,             # 0=lite, 1=full, 2=heavy
    enable_segmentation=False,      # Not needed for landmarks
    refine_face_landmarks=False,    # Faster without refinement
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
```

## Related Services

- **letter-model-service**: Consumes landmarks from Kinesis and produces letter predictions
- **agent-service**: Manages WebSocket connections to API Gateway (if separate)

## License

Part of the Glossa ASL Recognition System.

