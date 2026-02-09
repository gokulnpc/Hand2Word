#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import copy
import cv2 as cv
import websockets
import asyncio
import json
import sys
import os
import numpy as np
import mediapipe as mp
from utils import CvFpsCalc

def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", help='cap width', type=int, default=960)
    parser.add_argument("--height", help='cap height', type=int, default=540)
    parser.add_argument("--kinesis_ws_url", help='Kinesis ingress WebSocket URL (API Gateway)', 
                        type=str, default='wss://opcs2s86c2.execute-api.us-east-1.amazonaws.com/dev')
    parser.add_argument("--session_id", help='Session ID for Kinesis', type=str, default=None)

    parser.add_argument('--use_static_image_mode', action='store_true')
    parser.add_argument("--min_detection_confidence",
                        help='min_detection_confidence',
                        type=float,
                        default=0.5)
    parser.add_argument("--min_tracking_confidence",
                        help='min_tracking_confidence',
                        type=float,
                        default=0.5)

    args = parser.parse_args()
    return args

def extract_keypoints(results):
    """
    Extract keypoints from MediaPipe Holistic results.
    Order: pose → face → left_hand → right_hand (1662 total values)
    """
    pose = np.array([[res.x, res.y, res.z, res.visibility] for res in results.pose_landmarks.landmark]).flatten() if results.pose_landmarks else np.zeros(33*4)
    face = np.array([[res.x, res.y, res.z] for res in results.face_landmarks.landmark]).flatten() if results.face_landmarks else np.zeros(468*3)
    lh = np.array([[res.x, res.y, res.z] for res in results.left_hand_landmarks.landmark]).flatten() if results.left_hand_landmarks else np.zeros(21*3)
    rh = np.array([[res.x, res.y, res.z] for res in results.right_hand_landmarks.landmark]).flatten() if results.right_hand_landmarks else np.zeros(21*3)
    return np.concatenate([pose, face, lh, rh])

async def main():
    # Argument parsing
    args = get_args()

    cap_device = args.device
    cap_width = args.width
    cap_height = args.height
    kinesis_ws_url = args.kinesis_ws_url
    session_id = args.session_id or f"session_{int(asyncio.get_event_loop().time())}"

    use_static_image_mode = args.use_static_image_mode
    min_detection_confidence = args.min_detection_confidence
    min_tracking_confidence = args.min_tracking_confidence

    # Camera preparation
    cap = cv.VideoCapture(cap_device)
    cap.set(cv.CAP_PROP_FRAME_WIDTH, cap_width)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, cap_height)

    # MediaPipe Holistic model
    mp_holistic = mp.solutions.holistic
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles
    
    holistic = mp_holistic.Holistic(
        static_image_mode=use_static_image_mode,
        model_complexity=1,
        enable_segmentation=False,
        refine_face_landmarks=False,
        min_detection_confidence=min_detection_confidence,
        min_tracking_confidence=min_tracking_confidence
    )

    # FPS Measurement
    cvFpsCalc = CvFpsCalc(buffer_len=10)

    # Connect to Kinesis ingress WebSocket
    async with websockets.connect(kinesis_ws_url) as kinesis_ws:
        print(f"Connected to Kinesis ingress WebSocket at {kinesis_ws_url}")
        print(f"Session ID: {session_id}")
        print("Using MediaPipe Holistic for full-body tracking")
        
        try:
            while True:
                fps = cvFpsCalc.get_fps()

                # Process Key (ESC: end)
                key = cv.waitKey(10)
                if key == 27:  # ESC
                    await kinesis_ws.close(code=1000, reason="User requested exit")
                    break

                # Camera capture
                ret, image = cap.read()
                if not ret:
                    await kinesis_ws.close(code=1000, reason="Camera capture failed")
                    break
                    
                image = cv.flip(image, 1)  # Mirror display
                debug_image = copy.deepcopy(image)
                
                # Convert BGR to RGB for MediaPipe
                image_rgb = cv.cvtColor(image, cv.COLOR_BGR2RGB)
                image_rgb.flags.writeable = False

                # Process with MediaPipe Holistic
                results = holistic.process(image_rgb)
                
                image_rgb.flags.writeable = True

                # Extract keypoints (1662 values: pose + face + left_hand + right_hand)
                keypoints = extract_keypoints(results)
                
                # Send holistic landmarks to Kinesis (every frame)
                try:
                    kinesis_message = {
                        "action": "sendlandmarks",
                        "session_id": session_id,
                        "data": keypoints.tolist()  # Convert numpy array to list
                    }
                    await kinesis_ws.send(json.dumps(kinesis_message))
                    
                    # Draw holistic landmarks on debug image
                    # Draw pose
                    mp_drawing.draw_landmarks(
                        debug_image,
                        results.pose_landmarks,
                        mp_holistic.POSE_CONNECTIONS,
                        landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style()
                    )
                    
                    # Draw hands
                    mp_drawing.draw_landmarks(
                        debug_image,
                        results.left_hand_landmarks,
                        mp_holistic.HAND_CONNECTIONS,
                        mp_drawing_styles.get_default_hand_landmarks_style(),
                        mp_drawing_styles.get_default_hand_connections_style()
                    )
                    mp_drawing.draw_landmarks(
                        debug_image,
                        results.right_hand_landmarks,
                        mp_holistic.HAND_CONNECTIONS,
                        mp_drawing_styles.get_default_hand_landmarks_style(),
                        mp_drawing_styles.get_default_hand_connections_style()
                    )
                    
                    # Draw face (optional - can be commented out for cleaner display)
                    # mp_drawing.draw_landmarks(
                    #     debug_image,
                    #     results.face_landmarks,
                    #     mp_holistic.FACEMESH_CONTOURS,
                    #     landmark_drawing_spec=None,
                    #     connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_contours_style()
                    # )
                    
                except websockets.exceptions.ConnectionClosed:
                    print("WebSocket connection was closed")
                    break
                except Exception as e:
                    print(f"WebSocket error: {str(e)}")
                    await kinesis_ws.close(code=1000, reason=f"Error: {str(e)}")
                    break

                # Draw FPS
                debug_image = draw_info(debug_image, fps)

                # Screen reflection
                cv.imshow('ASL Holistic Recognition', debug_image)

        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection was closed")
        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            try:
                await kinesis_ws.close(code=1000, reason=f"Error: {str(e)}")
            except:
                pass
        finally:
            # Clean up MediaPipe Holistic
            holistic.close()
            # Release camera and destroy windows
            cap.release()
            cv.destroyAllWindows()

def draw_info(image, fps):
    cv.putText(image, "FPS:" + str(fps), (10, 30), cv.FONT_HERSHEY_SIMPLEX,
               1.0, (0, 0, 0), 4, cv.LINE_AA)
    cv.putText(image, "FPS:" + str(fps), (10, 30), cv.FONT_HERSHEY_SIMPLEX,
               1.0, (255, 255, 255), 2, cv.LINE_AA)
    return image

if __name__ == '__main__':
    asyncio.run(main())
