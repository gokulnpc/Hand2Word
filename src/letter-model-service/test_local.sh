#!/bin/bash
#
# Local Testing Script for ASL Model Serving Service
# This script helps you quickly test the service locally with proper environment setup
#

set -e  # Exit on error

echo "============================================================"
echo "ASL Model Serving Service - Local Test Runner"
echo "============================================================"
echo ""

# Load environment variables from .env if it exists
if [ -f .env ]; then
    echo "📝 Loading environment variables from .env..."
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "📝 No .env file found (using AWS SSO or environment variables)"
fi

# Set default values for Kinesis stream names if not provided
export LANDMARKS_STREAM_NAME=${LANDMARKS_STREAM_NAME:-"asl-landmarks-stream"}
export LETTERS_STREAM_NAME=${LETTERS_STREAM_NAME:-"asl-letters-stream"}
export AWS_REGION=${AWS_REGION:-"us-east-1"}
export POLLING_INTERVAL=${POLLING_INTERVAL:-"1"}
export ENABLE_TRACING=${ENABLE_TRACING:-"false"}

echo "✓ Configuration loaded"
echo "  Region: $AWS_REGION"
echo "  Landmarks Stream: $LANDMARKS_STREAM_NAME"
echo "  Letters Stream: $LETTERS_STREAM_NAME"
echo ""

# Check AWS credentials
echo "🔐 Verifying AWS credentials..."
if aws sts get-caller-identity > /dev/null 2>&1; then
    AWS_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text)
    AWS_USER=$(aws sts get-caller-identity --query 'Arn' --output text)
    echo "✓ AWS credentials are valid"
    echo "  Account: $AWS_ACCOUNT"
    echo "  Identity: $AWS_USER"
    
    # Check if using SSO
    if echo "$AWS_USER" | grep -q "assumed-role"; then
        echo "  Auth Method: AWS SSO (temporary credentials)"
    else
        echo "  Auth Method: IAM User or Access Keys"
    fi
else
    echo "❌ AWS credentials are invalid or AWS CLI is not configured"
    echo ""
    echo "To authenticate with AWS SSO, run:"
    echo "  aws sso login --profile your-profile-name"
    echo ""
    echo "Or set up AWS credentials:"
    echo "  aws configure"
    exit 1
fi
echo ""

# Check if Kinesis streams exist
echo "📊 Checking Kinesis streams..."
if aws kinesis describe-stream --stream-name $LANDMARKS_STREAM_NAME > /dev/null 2>&1; then
    echo "✓ Landmarks stream exists: $LANDMARKS_STREAM_NAME"
else
    echo "❌ Landmarks stream not found: $LANDMARKS_STREAM_NAME"
    echo "   Deploy Kinesis streams using Terraform first:"
    echo "   cd ../../iac && terraform apply"
    exit 1
fi

if aws kinesis describe-stream --stream-name $LETTERS_STREAM_NAME > /dev/null 2>&1; then
    echo "✓ Letters stream exists: $LETTERS_STREAM_NAME"
else
    echo "❌ Letters stream not found: $LETTERS_STREAM_NAME"
    exit 1
fi
echo ""

# Check if model files exist
echo "🤖 Checking model files..."
if [ -f "model/keypoint_classifier/keypoint_classifier.tflite" ]; then
    echo "✓ Model file found"
else
    echo "❌ Model file not found: model/keypoint_classifier/keypoint_classifier.tflite"
    exit 1
fi

if [ -f "model/keypoint_classifier/keypoint_classifier_label.csv" ]; then
    echo "✓ Model labels found"
else
    echo "⚠️  Model labels not found, will use fallback labels"
fi
echo ""

# Check and activate virtual environment
echo "📦 Checking virtual environment..."
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Creating..."
    if command -v uv &> /dev/null; then
        echo "  Using uv to create venv and install dependencies..."
        uv sync
    else
        echo "  Using python venv..."
        python3 -m venv .venv
        source .venv/bin/activate
        pip install boto3 tensorflow numpy opentelemetry-api opentelemetry-sdk
    fi
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment found"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
    echo "✓ Virtual environment activated (Windows)"
else
    echo "⚠️  Could not find activation script, continuing anyway..."
fi

# Verify dependencies are available
if python3 -c "import boto3, tensorflow, numpy" 2>/dev/null; then
    echo "✓ Core dependencies are available"
else
    echo "❌ Missing dependencies. Installing..."
    if command -v uv &> /dev/null; then
        echo "  Using uv to install dependencies..."
        uv sync
    else
        echo "  Using pip to install dependencies..."
        pip install boto3 tensorflow numpy opentelemetry-api opentelemetry-sdk
    fi
    echo "✓ Dependencies installed"
fi
echo ""

# Offer to run unit tests
echo "🧪 Would you like to run unit tests first? (y/n)"
read -r RUN_TESTS
if [ "$RUN_TESTS" == "y" ] || [ "$RUN_TESTS" == "Y" ]; then
    echo "Running unit tests..."
    if python3 -m pytest tests/ -v; then
        echo "✓ All tests passed"
    else
        echo "❌ Some tests failed"
        echo "Continue anyway? (y/n)"
        read -r CONTINUE
        if [ "$CONTINUE" != "y" ] && [ "$CONTINUE" != "Y" ]; then
            exit 1
        fi
    fi
    echo ""
fi

# Start the service
echo "============================================================"
echo "🚀 Starting ASL Model Serving Service..."
echo "============================================================"
echo ""
echo "Press Ctrl+C to stop the service"
echo ""
sleep 2

# Run the service
python3 main.py

echo ""
echo "============================================================"
echo "Service stopped"
echo "============================================================"

