#!/bin/bash
# Build, tag and push Docker image with latest and manifest version tags.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$SCRIPT_DIR/../__manifest__.py"
IMAGE="oduist/connect-elevenlabs-agent"

# Extract version from Odoo manifest
VERSION=$(grep -oP "(?<='version':\s')[^']+" "$MANIFEST")
if [ -z "$VERSION" ]; then
    echo "Error: could not extract version from $MANIFEST"
    exit 1
fi

echo "Building $IMAGE (version: $VERSION)..."
docker build -t "$IMAGE:latest" -t "$IMAGE:$VERSION" "$SCRIPT_DIR"

echo "Pushing $IMAGE:latest..."
docker push "$IMAGE:latest"

echo "Pushing $IMAGE:$VERSION..."
docker push "$IMAGE:$VERSION"

echo "Done: $IMAGE:latest and $IMAGE:$VERSION pushed."
