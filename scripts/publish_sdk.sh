#!/bin/bash
set -e

# Navigate to SDK directory
cd "$(dirname "$0")/../sdk/python"

echo "📦 Preparing to publish facto-ai to PyPI..."

# Ensure build tools are installed
pip install build twine

# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build package
echo "🔨 Building package..."
python -m build

# Check package
echo "🔍 Checking package via Twine..."
twine check dist/*

echo "✅ Build successful!"
echo ""
echo "To publish to PyPI, run:"
echo "  twine upload dist/*"
echo ""
echo "You will be prompted for your PyPI username and password (or API token)."
