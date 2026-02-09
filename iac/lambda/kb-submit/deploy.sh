#!/bin/bash
# Deploy script for KB Submit Lambda

set -e

echo "Building KB Submit Lambda deployment package..."

# Clean up old deployment
rm -rf package deployment.zip

# Create package directory
mkdir -p package

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt -t package/

# Copy Lambda function
cp lambda_function.py package/

# Create deployment package
echo "Creating deployment.zip..."
cd package
zip -r ../deployment.zip . -x "*.pyc" -x "__pycache__/*"
cd ..

# Clean up
rm -rf package

echo "Deployment package created: deployment.zip"
echo "Size: $(du -h deployment.zip | cut -f1)"
echo ""
echo "Next steps:"
echo "1. cd ../../iac"
echo "2. terraform init"
echo "3. terraform apply"

