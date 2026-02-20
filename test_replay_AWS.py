#!/usr/bin/env python3
"""
Test script to replay real hand landmarks captured from test_landmarks.txt.
This replays the exact sequence of "AWS" with realistic timing based on the original log timestamps.
"""

import asyncio
import websockets
import json
import sys
import numpy as np
from datetime import datetime

def load_test_data(filename="test_data_AWS.json"):
    """Load the test data from JSON file."""
    with open(filename, 'r') as f:
        return json.load(f)

def convert_hand_landmarks_to_holistic(hand_coordinates, hand_side="left"):
    """
    Convert 21-point hand landmarks (x, y) to holistic format (1662 values).
    
    Args:
        hand_coordinates: List of [x, y] coordinates (21 points)
        hand_side: "left" or "right"
    
    Returns:
        List of 1662 values in holistic format (pose, face, left_hand, right_hand)
    """
    # Pose landmarks: 33 points × 4 (x, y, z, visibility) = 132 values (all zeros)
    pose = [0.0] * (33 * 4)
    
    # Face landmarks: 468 points × 3 (x, y, z) = 1404 values (all zeros)
    face = [0.0] * (468 * 3)
    
    # Hand landmarks: 21 points × 3 (x, y, z) = 63 values each
    # Convert [x, y] to [x, y, z=0.0] and flatten
    hand_data = []
    for point in hand_coordinates:
        hand_data.extend([point[0], point[1], 0.0])  # Add z=0.0 for each point
    
    # Assign to correct hand position
    if hand_side == "left":
        left_hand = hand_data
        right_hand = [0.0] * (21 * 3)
    else:  # right
        left_hand = [0.0] * (21 * 3)
        right_hand = hand_data
    
    # Concatenate: pose (132) + face (1404) + left_hand (63) + right_hand (63) = 1662
    return pose + face + left_hand + right_hand

async def replay_landmarks(ws_url, test_data):
    """
    Replay the landmark sequence with realistic timing and receive resolved words.
    
    Args:
        ws_url: WebSocket URL (API Gateway endpoint)
        test_data: Loaded test data dictionary
    """
    session_id = test_data["session_id"]
    sequence = test_data["sequence"]
    landmarks = test_data["landmarks"]
    
    print("=" * 80)
    print(f"Replaying Real Hand Landmarks: '{sequence}'")
    print("=" * 80)
    print(f"WebSocket URL: {ws_url}")
    print(f"Session ID: {session_id}")
    print(f"Total frames: {len(landmarks)}")
    print(f"Description: {test_data['description']}")
    print("=" * 80)
    print()
    
    # Track received messages
    resolved_words = []
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print("✓ Connected to WebSocket API Gateway")
            print()
            
            # Create async task to receive messages from WebSocket
            async def receive_messages():
                try:
                    async for message in websocket:
                        data = json.loads(message)
                        if data.get('type') == 'resolved_word':
                            resolved_data = data.get('data', {})
                            raw_word = resolved_data.get('raw_word', '')
                            results = resolved_data.get('all_results', [])
                            
                            print("\n" + "=" * 80)
                            print(f"🔤 RESOLVED WORD RECEIVED")
                            print("=" * 80)
                            print(f"Raw word: {raw_word}")
                            
                            if results:
                                print(f"\nTop 5 Results:")
                                for i, result in enumerate(results[:5], 1):
                                    print(f"  {i}. {result['surface']:20} "
                                          f"(atlas: {result['atlas_score']:.3f}, "
                                          f"alias: {result['alias_confidence']:.3f}, "
                                          f"hybrid: {result['hybrid_score']:.3f})")
                            else:
                                print("No results (UNRESOLVED)")
                            
                            print("=" * 80)
                            
                            resolved_words.append({
                                'raw_word': raw_word,
                                'results': results
                            })
                        else:
                            print(f"Received message: {data}")
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    print(f"Error receiving message: {str(e)}")
            
            # Start receiving task
            receive_task = asyncio.create_task(receive_messages())
            print("✓ Listening for resolved words from outbound Lambda...")
            print()
            
            start_time = asyncio.get_event_loop().time()
            
            for i, frame in enumerate(landmarks):
                # Calculate delay based on original timestamp
                target_time = start_time + (frame["timestamp_ms"] / 1000.0)
                current_time = asyncio.get_event_loop().time()
                delay = target_time - current_time
                
                if delay > 0:
                    await asyncio.sleep(delay)
                
                # Check if this is a skip event (no_hands)
                if frame.get("skip", False):
                    elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
                    print(f"[{i+1:2d}/{len(landmarks):2d}] "
                          f"t={elapsed_ms:4d}ms | "
                          f"⊗ {frame['event']:10s} | "
                          f"(skip - no data sent)")
                    continue
                
                # Convert hand landmarks to holistic format
                holistic_landmarks = convert_hand_landmarks_to_holistic(
                    frame["coordinates"],
                    frame["hand"]
                )
                
                # Create message
                message = {
                    "action": "sendlandmarks",
                    "session_id": session_id,
                    "data": holistic_landmarks
                }
                
                # Send message
                await websocket.send(json.dumps(message))
                
                # Display progress
                elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
                print(f"[{i+1:2d}/{len(landmarks):2d}] "
                      f"t={elapsed_ms:4d}ms | "
                      f"{frame['letter']} (conf={frame['confidence']:.2f}) | "
                      f"hand={frame['hand']:5s} | "
                      f"✓ Sent {len(holistic_landmarks)} values")
                
                # Optional: small buffer to prevent overwhelming the server
                # (Comment out if you want exact timing)
                # await asyncio.sleep(0.001)
            
            # Wait for word finalization and outbound Lambda response
            print()
            print("Waiting 10 seconds for word finalization and outbound Lambda response...")
            await asyncio.sleep(10.0)

            # Cancel receive task and close connection gracefully
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
            
            await websocket.close(code=1000, reason="Replay completed")
            
            # Print summary
            print("\n" + "=" * 80)
            print("TEST SUMMARY")
            print("=" * 80)
            print(f"Sent {len(landmarks)} landmark frames for: '{sequence}'")
            print(f"Received {len(resolved_words)} resolved word(s) from outbound Lambda")
            
            if resolved_words:
                for i, rw in enumerate(resolved_words, 1):
                    print(f"\nResolved Word {i}:")
                    print(f"  Raw: {rw['raw_word']}")
                    if rw['results']:
                        top = rw['results'][0]
                        print(f"  Top Match: {top['surface']} (hybrid: {top['hybrid_score']:.3f})")
                    else:
                        print(f"  Top Match: UNRESOLVED")
            else:
                print("\n⚠️  WARNING: No resolved words received from outbound Lambda!")
                print("   Check that:")
                print("   1. Word-resolver service is running")
                print("   2. Letter-model service is running")
                print("   3. Outbound Lambda has correct permissions")
                print("   4. DynamoDB has session_id mapping")
            
            print("=" * 80)
            
    except websockets.exceptions.WebSocketException as e:
        print(f"\n✗ WebSocket error: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return len(resolved_words) > 0

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_replay_AWS.py <websocket_url> [test_data_file]")
        print()
        print("Arguments:")
        print("  websocket_url   : WebSocket API Gateway endpoint")
        print("  test_data_file  : JSON file with test data (default: test_data_AWS.json)")
        print()
        print("Example:")
        print("  python3 test_replay_AWS.py wss://opcs2s86c2.execute-api.us-east-1.amazonaws.com/dev")
        print()
        print("This script replays the exact hand landmarks from test_landmarks.txt,")
        print("spelling 'AWS' with realistic timing (~3.8 seconds total).")
        sys.exit(1)
    
    ws_url = sys.argv[1]
    test_data_file = sys.argv[2] if len(sys.argv) > 2 else "test_data_AWS.json"
    
    # Load test data
    try:
        test_data = load_test_data(test_data_file)
    except FileNotFoundError:
        print(f"✗ Error: Test data file '{test_data_file}' not found!")
        print()
        print("Make sure test_data_AWS.json is in the current directory.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Error: Invalid JSON in '{test_data_file}': {e}")
        sys.exit(1)
    
    # Run the replay
    success = asyncio.run(replay_landmarks(ws_url, test_data))
    
    if success:
        print("\n✓ Test completed successfully - received resolved word(s) from outbound Lambda!")
        sys.exit(0)
    else:
        print("\n✗ Test failed - no resolved words received!")
        sys.exit(1)

if __name__ == "__main__":
    main()

