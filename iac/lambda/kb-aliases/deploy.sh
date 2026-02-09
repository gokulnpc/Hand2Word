#!/bin/bash
set -e

echo "Building KB Aliases Lambda deployment package..."

# Clean up old deployment
rm -rf package deployment.zip

# Create package directory
mkdir -p package

# Install dependencies for Lambda (Python 3.12, Linux x86_64)
if [ -f requirements.txt ]; then
    echo "Installing dependencies for Lambda runtime (Python 3.12, x86_64)..."
    # Use the correct platform and python version for Lambda
    pip install -r requirements.txt \
        --python-version 3.12 \
        --platform manylinux2014_x86_64 \
        --target package/ \
        --only-binary=:all: \
        --upgrade
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

