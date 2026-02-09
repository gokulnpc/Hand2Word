#!/bin/bash
set -e

echo "Building KB Ingest Lambda deployment package..."

# Clean up old deployment
rm -rf package deployment.zip

# Create package directory
mkdir -p package

# Install dependencies
if [ -f requirements.txt ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt -t package/ --quiet
fi

# Copy Lambda function
cp lambda_function.py package/

# Create deployment zip
cd package
zip -r ../deployment.zip . -q
cd ..

# Clean up
rm -rf package

echo "Deployment package created: deployment.zip"
du -h deployment.zip | awk '{print "Size: " $1}'

echo ""
echo "Next steps:"
echo "1. cd ../../iac"
echo "2. terraform init"
echo "3. terraform apply"

