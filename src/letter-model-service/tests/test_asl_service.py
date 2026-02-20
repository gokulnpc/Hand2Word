"""
Unit tests for Letter ASL Service (Kinesis Consumer/Producer version)
Tests the core letter ASL prediction logic without HTTP/WebSocket dependencies.
"""

import pytest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timezone
from services.asl_service import LetterASLService


@pytest.fixture
def mock_keypoint_classifier():
    """Mock keypoint classifier"""
    mock_classifier = MagicMock()
    mock_classifier.return_value = 11  # Returns class ID for "ASL B" (index 11 in labels)
    return mock_classifier


@pytest.fixture
def letter_asl_service(mock_keypoint_classifier):
    """Create Letter ASL service instance with mocked dependencies"""
    with patch('services.asl_service.KeyPointClassifier') as mock_classifier_class:
        mock_classifier_class.return_value = mock_keypoint_classifier
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open_csv_labels()):
                service = LetterASLService()
                service.keypoint_classifier = mock_keypoint_classifier
                return service


@pytest.fixture
def sample_landmarks():
    """Sample landmark data for testing (21 landmarks with x, y coordinates)"""
    return [[0.1 + i * 0.01, 0.2 + i * 0.01] for i in range(21)]


class TestLetterASLService:
    """Test suite for LetterASLService"""
    
    @pytest.mark.asyncio
    async def test_predict_from_landmarks_success(self, letter_asl_service, sample_landmarks):
        """Test successful prediction from landmarks"""
        result = await letter_asl_service.predict_from_landmarks(sample_landmarks, "test_user")
        
        assert isinstance(result, dict)
        assert result["prediction"] == "ASL B"
        assert result["confidence"] == 0.95
        assert result["user_id"] == "test_user"
        assert "timestamp" in result
        assert "processing_time_ms" in result
        assert isinstance(result["processing_time_ms"], (int, float))
    
    @pytest.mark.asyncio
    async def test_predict_from_landmarks_anonymous_user(self, letter_asl_service, sample_landmarks):
        """Test prediction with anonymous user (no user_id)"""
        result = await letter_asl_service.predict_from_landmarks(sample_landmarks, None)
        
        assert result["user_id"] is None
        assert result["prediction"] == "ASL B"
    
    @pytest.mark.asyncio
    async def test_predict_from_landmarks_model_not_initialized(self):
        """Test prediction when model is not initialized"""
        with patch('services.asl_service.KeyPointClassifier') as mock_classifier:
            mock_classifier.side_effect = RuntimeError("Model init failed")
            
            with pytest.raises(RuntimeError) as exc_info:
                service = LetterASLService()
            
            assert "Failed to initialize ASL model" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_predict_from_landmarks_invalid_input_length(self, letter_asl_service):
        """Test prediction with invalid input length (too few landmarks)"""
        invalid_landmarks = [[0.1, 0.2], [0.3, 0.4]]  # Only 2 landmarks instead of 21
        
        with pytest.raises(ValueError) as exc_info:
            await letter_asl_service.predict_from_landmarks(invalid_landmarks, "test_user")
        
        assert "Expected 42 pre-processed landmark coordinates" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_predict_from_landmarks_unknown_prediction(self, letter_asl_service, sample_landmarks):
        """Test prediction with unknown/invalid class ID"""
        # Mock classifier to return invalid class ID
        letter_asl_service.keypoint_classifier.return_value = 999
        
        result = await letter_asl_service.predict_from_landmarks(sample_landmarks, "test_user")
        
        assert result["prediction"] == "Unknown"
        assert result["confidence"] == 0.1  # Low confidence for unknown
    
    @pytest.mark.asyncio
    async def test_predict_from_landmarks_classifier_exception(self, letter_asl_service, sample_landmarks):
        """Test prediction when classifier raises exception"""
        # Mock classifier to raise exception
        letter_asl_service.keypoint_classifier.side_effect = Exception("Classifier error")
        
        with pytest.raises(RuntimeError) as exc_info:
            await letter_asl_service.predict_from_landmarks(sample_landmarks, "test_user")
        
        assert "Prediction failed" in str(exc_info.value)
    
    def test_get_available_signs_success(self, letter_asl_service):
        """Test getting list of available signs"""
        signs = letter_asl_service.get_available_signs()
        
        assert isinstance(signs, list)
        assert len(signs) > 0
        assert "ASL A" in signs
        assert "ASL B" in signs
        assert "ASL Z" in signs
    
    def test_get_available_signs_model_not_initialized(self):
        """Test getting signs when model is not initialized"""
        service = LetterASLService.__new__(LetterASLService)  # Create without __init__
        service.model_initialized = False
        
        with pytest.raises(RuntimeError) as exc_info:
            service.get_available_signs()
        
        assert "ASL model not initialized" in str(exc_info.value)
    
    def test_is_ready_true(self, letter_asl_service):
        """Test is_ready returns True when model is initialized"""
        assert letter_asl_service.is_ready() is True
    
    def test_is_ready_false(self):
        """Test is_ready returns False when model is not initialized"""
        service = LetterASLService.__new__(LetterASLService)  # Create without __init__
        service.model_initialized = False
        assert service.is_ready() is False
    
    def test_pre_process_landmark(self, letter_asl_service, sample_landmarks):
        """Test landmark preprocessing"""
        result = letter_asl_service.pre_process_landmark(sample_landmarks)
        
        assert isinstance(result, list)
        assert len(result) == 42  # 21 landmarks * 2 coordinates
        assert all(isinstance(x, (int, float)) for x in result)
        
        # Check that normalization occurred (values should be between -1 and 1)
        assert all(-1 <= x <= 1 for x in result)
    
    def test_pre_process_landmark_single_point(self, letter_asl_service):
        """Test preprocessing with single landmark point"""
        single_landmark = [[0.5, 0.5]]
        result = letter_asl_service.pre_process_landmark(single_landmark)
        
        assert len(result) == 2
        assert result == [0.0, 0.0]  # Should be normalized to origin
    
    def test_serialize_response_datetime(self, letter_asl_service):
        """Test serialization of datetime objects"""
        test_data = {
            "timestamp": datetime.now(timezone.utc),
            "value": "test"
        }
        
        result = letter_asl_service._serialize_response(test_data)
        
        assert isinstance(result["timestamp"], str)
        assert result["value"] == "test"
    
    def test_serialize_response_nested(self, letter_asl_service):
        """Test serialization of nested objects"""
        test_data = {
            "nested": {
                "timestamp": datetime.now(timezone.utc),
                "value": 123
            },
            "simple": "value"
        }
        
        result = letter_asl_service._serialize_response(test_data)
        
        assert isinstance(result["nested"]["timestamp"], str)
        assert result["nested"]["value"] == 123
        assert result["simple"] == "value"


# Helper function for mocking CSV file reading
def mock_open_csv_labels():
    """Mock open function for CSV label file"""
    csv_content = """ASL 0
ASL 1
ASL 2
ASL 3
ASL 4
ASL 5
ASL 6
ASL 7
ASL 8
ASL 9
ASL A
ASL B
ASL C
ASL D
ASL E
ASL F
ASL G
ASL H
ASL I
ASL J
ASL K
ASL L
ASL M
ASL N
ASL O
ASL P
ASL Q
ASL R
ASL S
ASL T
ASL U
ASL V
ASL W
ASL X
ASL Y
ASL Z
ASL _"""
    
    from unittest.mock import mock_open as mo
    return mo(read_data=csv_content)

