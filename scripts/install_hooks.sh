#!/bin/bash
#
# Install Git Hooks for Facto
#
# This script configures git to use the .githooks directory for hooks.
# Run this once after cloning the repo.
#

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.githooks"

echo "Installing Facto git hooks..."

# Configure git to use our hooks directory
git config core.hooksPath "$HOOKS_DIR"

# Make hooks executable
chmod +x "$HOOKS_DIR"/*

echo "✅ Git hooks installed!"
echo ""
echo "The following hooks are now active:"
ls -la "$HOOKS_DIR"
echo ""
echo "Pre-push hook will run tests before each push."
echo "To bypass (not recommended): git push --no-verify"
