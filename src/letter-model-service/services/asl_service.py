import csv
import copy
import itertools
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import numpy as npFA
from constant.config import ENABLE_TRACING
from model import KeyPointClassifier
import os

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
# Log extracted hand landmarks for testing/debugging
import logging
logger = logging.getLogger(__name__)

class LetterASLService:
    # MediaPipe Holistic landmark structure
    # Order: pose → face → left_hand → right_hand (as per your extract_keypoints)
    POSE_LANDMARKS = 33   # Body pose (33 × 4 = 132 values with x,y,z,visibility)
    FACE_LANDMARKS = 468  # Face mesh (468 × 3 = 1404 values)
    HAND_LANDMARKS = 21   # Per hand (21 × 3 = 63 values per hand)
    
    # Offsets in the flattened array (matching your extract_keypoints order)
    POSE_START = 0
    POSE_END = POSE_LANDMARKS * 4  # 132
    FACE_START = POSE_END
    FACE_END = FACE_START + (FACE_LANDMARKS * 3)  # 132 + 1404 = 1536
    LEFT_HAND_START = FACE_END
    LEFT_HAND_END = LEFT_HAND_START + (HAND_LANDMARKS * 3)  # 1536 + 63 = 1599
    RIGHT_HAND_START = LEFT_HAND_END
    RIGHT_HAND_END = RIGHT_HAND_START + (HAND_LANDMARKS * 3)  # 1599 + 63 = 1662
    
    def __init__(self):
        """Initialize the Letter ASL service with the keypoint classifier and labels."""
        self.keypoint_classifier = None
        self.keypoint_classifier_labels = []
        self.model_initialized = False
        
        # Only initialize tracer if tracing is enabled
        self.tracing_enabled = ENABLE_TRACING.lower() == "true"
        if self.tracing_enabled:
            self.tracer = trace.get_tracer(__name__)
        else:
            self.tracer = None
            
        self._initialize_model()
    
    def _create_span(self, name: str):
        """Create a span only if tracing is enabled, otherwise return a no-op context manager."""
        if self.tracing_enabled and self.tracer:
            return self.tracer.start_as_current_span(name)
        else:
            # Return a no-op context manager
            from contextlib import nullcontext
            return nullcontext()
    
    def _serialize_response(self, obj: Dict) -> Dict:
        """Convert datetime and ObjectId objects to strings"""
        serialized = {}
        for key, value in obj.items():
            if isinstance(value, datetime):
                serialized[key] = value.isoformat()
            elif isinstance(value, dict):
                serialized[key] = self._serialize_response(value)
            else:
                serialized[key] = value
        return serialized
    
    def _initialize_model(self):
        """Initialize the keypoint classifier and load labels."""
        with self._create_span("asl_model_initialization") as span:
            try:
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("model.type", "keypoint_classifier")
                
                # Initialize the keypoint classifier
                self.keypoint_classifier = KeyPointClassifier()
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("model.classifier.initialized", True)
                
                # Load labels
                label_path = 'model/keypoint_classifier/keypoint_classifier_label.csv'
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("model.label_path", label_path)
                
                if os.path.exists(label_path):
                    with open(label_path, encoding='utf-8-sig') as f:
                        keypoint_classifier_labels = csv.reader(f)
                        self.keypoint_classifier_labels = [
                            row[0] for row in keypoint_classifier_labels
                        ]
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("model.labels.source", "file")
                else:
                    # Fallback labels if file doesn't exist
                    self.keypoint_classifier_labels = [
                        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
                        "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T",
                        "U", "V", "W", "X", "Y", "Z", "_"
                    ]
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("model.labels.source", "fallback")
                
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("model.labels.count", len(self.keypoint_classifier_labels))
                self.model_initialized = True
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("model.initialization.success", True)
                
            except Exception as e:
                if span and hasattr(span, 'record_exception'):
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("model.initialization.success", False)
                print(f"Error initializing ASL model: {str(e)}")
                self.model_initialized = False
                raise RuntimeError(f"Failed to initialize ASL model: {str(e)}")
    
    def extract_hand_from_holistic(self, holistic_landmarks: List[float]) -> Dict[str, Any]:
        """
        Extract hand landmarks from MediaPipe Holistic output and determine handedness.
        
        Fingerspelling uses ONE dominant hand only.
        If both hands are active → skip inference (likely word-level or classifier sign).
        
        Args:
            holistic_landmarks: Flattened array from MediaPipe Holistic
                                (~1662 values: face, pose, left_hand, right_hand)
        
        Returns:
            Dictionary with:
                - hand_landmarks: List[List[float]] (21 points × 2 coords) or None
                - handedness: "left" or "right" or None
                - multi_hand: bool (True if both hands active)
                - skip_inference: bool (True if should skip letter prediction)
        """
        with self._create_span("hand_extraction") as span:
            result = {
                "hand_landmarks": None,
                "handedness": None,
                "multi_hand": False,
                "skip_inference": False
            }
            
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("input.holistic_values", len(holistic_landmarks))
            
            # Extract left and right hand landmarks
            left_hand_data = holistic_landmarks[self.LEFT_HAND_START:self.LEFT_HAND_END]
            right_hand_data = holistic_landmarks[self.RIGHT_HAND_START:self.RIGHT_HAND_END]
            
            # Check if hands are active (non-zero values indicate detected hand)
            left_hand_active = any(abs(val) > 0.01 for val in left_hand_data)
            right_hand_active = any(abs(val) > 0.01 for val in right_hand_data)
            
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("left_hand.active", left_hand_active)
                span.set_attribute("right_hand.active", right_hand_active)
            
            # Check for multi-hand scenario (both hands active)
            if left_hand_active and right_hand_active:
                result["multi_hand"] = True
                result["skip_inference"] = True
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("decision", "skip_multi_hand")
                    span.set_attribute("skip_reason", "both_hands_active_word_level_sign")
                return result
            
            # Single hand active: extract landmarks
            if right_hand_active:
                hand_data = right_hand_data
                result["handedness"] = "right"
            elif left_hand_active:
                hand_data = left_hand_data
                result["handedness"] = "left"
            else:
                # No hands detected
                result["skip_inference"] = True
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("decision", "skip_no_hands")
                    span.set_attribute("skip_reason", "no_hands_detected")
                return result
            
            # Reshape hand data: 63 values → 21 points × 3 coords → extract only x, y
            hand_landmarks = []
            for i in range(0, len(hand_data), 3):
                x, y = hand_data[i], hand_data[i+1]
                # z coordinate (hand_data[i+2]) is ignored for 2D model
                hand_landmarks.append([x, y])
            
            result["hand_landmarks"] = hand_landmarks
            
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("decision", "single_hand_detected")
                span.set_attribute("hand.selected", result["handedness"])
                span.set_attribute("hand.landmarks.count", len(hand_landmarks))
            
            logger.info(f"[HAND_LANDMARKS] hand={result['handedness']}, landmarks={hand_landmarks}")
            
            return result
    
    def pre_process_landmark(self, landmark_list: List[List[float]]) -> List[float]:
        """
        Pre-process landmark coordinates for model prediction.
        Converts to relative coordinates and normalizes.
        
        Args:
            landmark_list: List of [x, y] landmark coordinates
            
        Returns:
            List of normalized coordinate values
        """
        with self._create_span("landmark_preprocessing") as span:
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("landmarks.input.count", len(landmark_list))
            
            temp_landmark_list = copy.deepcopy(landmark_list)

            # Convert to relative coordinates
            base_x, base_y = 0, 0
            for index, landmark_point in enumerate(temp_landmark_list):
                if index == 0:
                    base_x, base_y = landmark_point[0], landmark_point[1]
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("landmarks.base.x", base_x)
                        span.set_attribute("landmarks.base.y", base_y)

                temp_landmark_list[index][0] = temp_landmark_list[index][0] - base_x
                temp_landmark_list[index][1] = temp_landmark_list[index][1] - base_y

            # Convert to a one-dimensional list
            temp_landmark_list = list(
                itertools.chain.from_iterable(temp_landmark_list)) 

            # Normalization
            # max_value is the maximum absolute value in the list
            max_value = max(list(map(abs, temp_landmark_list)))
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("landmarks.normalization.max_value", max_value)

            def normalize_(n):
                return n / max_value if max_value != 0 else 0

            temp_landmark_list = list(map(normalize_, temp_landmark_list))
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("landmarks.output.count", len(temp_landmark_list))

            return temp_landmark_list
    
    async def predict_from_landmarks(
        self, 
        landmarks_list: List[float],  # Changed: now accepts flattened holistic array
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Predict ASL sign from MediaPipe Holistic landmark data.
        
        Args:
            landmarks_list: Flattened MediaPipe Holistic landmarks (~1662 values)
            user_id: Optional user ID for tracking
            
        Returns:
            Dictionary containing prediction results and metadata
        """
        with self._create_span("asl_prediction") as span:
            start_time = datetime.now(timezone.utc)
            
            # Add span attributes for tracking
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("prediction.user_id", user_id or "anonymous")
                span.set_attribute("prediction.input.holistic_values", len(landmarks_list))
                span.set_attribute("prediction.timestamp", start_time.isoformat())
            
            try:
                if not self.model_initialized:
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("prediction.error", "model_not_initialized")
                        span.set_status(Status(StatusCode.ERROR, "ASL model not initialized"))
                    raise RuntimeError("ASL model not initialized")
                
                # Extract hand landmarks and check for multi-hand scenario
                hand_extraction = self.extract_hand_from_holistic(landmarks_list)
                
                # Check if we should skip inference (multi-hand or no hands)
                if hand_extraction["skip_inference"]:
                    end_time = datetime.now(timezone.utc)
                    processing_time_ms = (end_time - start_time).total_seconds() * 1000
                    
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("prediction.skipped", True)
                        span.set_attribute("prediction.skip_reason", 
                                         "multi_hand" if hand_extraction["multi_hand"] else "no_hands")
                        span.set_attribute("prediction.processing_time_ms", round(processing_time_ms, 2))
                    
                    return {
                        "prediction": None,
                        "confidence": 0.0,
                        "timestamp": end_time.isoformat(),
                        "processing_time_ms": round(processing_time_ms, 2),
                        "user_id": user_id,
                        "skipped": True,
                        "skip_reason": "multi_hand" if hand_extraction["multi_hand"] else "no_hands",
                        "multi_hand": hand_extraction["multi_hand"],
                        "handedness": hand_extraction["handedness"]
                    }
                
                # Get extracted hand landmarks
                hand_landmarks = hand_extraction["hand_landmarks"]
                handedness = hand_extraction["handedness"]
                
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("prediction.handedness", handedness)
                    span.set_attribute("prediction.hand_landmarks_count", len(hand_landmarks))
                
                # Pre-process landmarks with tracing
                pre_processed_landmarks = self.pre_process_landmark(hand_landmarks)
                
                # Validate input data
                if len(pre_processed_landmarks) != 42:
                    if span and hasattr(span, 'set_attribute'):
                        span.set_attribute("prediction.error", "invalid_input_length")
                        span.set_attribute("prediction.input.expected_length", 42)
                        span.set_attribute("prediction.input.actual_length", len(pre_processed_landmarks))
                        span.set_status(Status(StatusCode.ERROR, "Invalid input length"))
                    raise ValueError(f"Expected 42 pre-processed landmark coordinates, got {len(pre_processed_landmarks)}")
                
                # Model prediction with tracing
                with self._create_span("model_inference") as inference_span:
                    if inference_span and hasattr(inference_span, 'set_attribute'):
                        inference_span.set_attribute("model.input.features", len(pre_processed_landmarks))
                    
                    # Data is already pre-processed, pass it directly to the model
                    # Model now returns (class_id, confidence_score)
                    hand_sign_id, confidence = self.keypoint_classifier(pre_processed_landmarks)
                    
                    if inference_span and hasattr(inference_span, 'set_attribute'):
                        inference_span.set_attribute("model.output.class_id", hand_sign_id)
                        inference_span.set_attribute("model.output.confidence", confidence)
                        inference_span.set_attribute("model.output.valid", 0 <= hand_sign_id < len(self.keypoint_classifier_labels))
                
                # Get the predicted label
                if 0 <= hand_sign_id < len(self.keypoint_classifier_labels):
                    prediction = self.keypoint_classifier_labels[hand_sign_id]
                    # Remove "ASL " prefix if present (model was trained with this prefix)
                    if prediction.startswith("ASL "):
                        prediction = prediction[4:]  # Strip "ASL " prefix
                else:
                    prediction = "Unknown"
                    confidence = 0.0   # Zero confidence for unknown/invalid predictions
                
                # Calculate processing time
                end_time = datetime.now(timezone.utc)
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                
                # Add prediction results to span
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("prediction.result", prediction)
                    span.set_attribute("prediction.confidence", confidence)
                    span.set_attribute("prediction.processing_time_ms", round(processing_time_ms, 2))
                    span.set_attribute("prediction.handedness", handedness)
                    span.set_attribute("prediction.success", True)
                
                response_data = {
                    "prediction": prediction,
                    "confidence": confidence,
                    "timestamp": end_time.isoformat(),
                    "processing_time_ms": round(processing_time_ms, 2),
                    "user_id": user_id,
                    "handedness": handedness,  # Include which hand was used
                    "multi_hand": False,  # Explicitly mark as single-hand prediction
                    "skipped": False
                }
                
                return response_data
                
            except (RuntimeError, ValueError) as e:
                if span and hasattr(span, 'record_exception'):
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("prediction.success", False)
                raise e
            except Exception as e:
                end_time = datetime.now(timezone.utc)
                processing_time_ms = (end_time - start_time).total_seconds() * 1000
                
                if span and hasattr(span, 'record_exception'):
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("prediction.success", False)
                    span.set_attribute("prediction.processing_time_ms", round(processing_time_ms, 2))
                
                raise RuntimeError(f"Prediction failed: {str(e)}")
    
    def get_available_signs(self) -> List[str]:
        """
        Get list of available ASL signs that can be predicted.
        
        Returns:
            List of ASL sign labels
        """
        if not self.model_initialized:
            raise RuntimeError("ASL model not initialized")
        return self.keypoint_classifier_labels.copy()
    
    def is_ready(self) -> bool:
        """
        Check if the service is ready to make predictions.
        
        Returns:
            True if model is initialized and ready
        """
        return self.model_initialized