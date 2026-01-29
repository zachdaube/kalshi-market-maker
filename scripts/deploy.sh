#!/bin/bash
# Deploy Kalshi Market Maker to DigitalOcean

set -e

DROPLET_IP="159.203.108.164"
DROPLET_USER="root"
REMOTE_DIR="/opt/kalshi-market-maker"
SCRIPT_DIR="$(dirname "$0")"
PROJECT_DIR="$SCRIPT_DIR/.."

echo "=== Kalshi Market Maker Deployment ==="
echo "Target: $DROPLET_USER@$DROPLET_IP"
echo ""

cd "$PROJECT_DIR"

# Run tests first (unless --skip-tests flag is passed)
if [ "$1" != "--skip-tests" ]; then
    echo "[0/4] Running tests before deployment..."
    if ! python -m pytest tests/ -v --tb=short; then
        echo ""
        echo "❌ Tests failed! Fix the errors before deploying."
        echo "   Run 'pytest tests/ -v' to see details."
        echo "   Or use './scripts/deploy.sh --skip-tests' to skip (not recommended)"
        exit 1
    fi
    echo "✓ All tests passed!"
    echo ""
else
    echo "[0/4] Skipping tests (--skip-tests flag)"
    echo ""
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

echo "[1/4] Setting up server (first time only)..."
ssh $SSH_OPTS $DROPLET_USER@$DROPLET_IP << 'SETUP'
# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
fi

# Install Docker Compose plugin if not present
if ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose..."
    apt-get update && apt-get install -y docker-compose-plugin
fi

# Create app directory
mkdir -p /opt/kalshi-market-maker
echo "Server setup complete!"
SETUP

echo "[2/4] Syncing project files..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '.env' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    -e "ssh $SSH_OPTS" \
    ./ $DROPLET_USER@$DROPLET_IP:$REMOTE_DIR/

echo "[3/4] Building and starting containers..."
ssh $SSH_OPTS $DROPLET_USER@$DROPLET_IP << DEPLOY
cd $REMOTE_DIR
docker compose down 2>/dev/null || true
docker compose up -d --build
DEPLOY

echo "[4/4] Verifying deployment..."
sleep 3
ssh $SSH_OPTS $DROPLET_USER@$DROPLET_IP "docker ps --filter name=kalshi"

echo ""
echo "=== Deployment Complete ==="
echo "Dashboard: http://$DROPLET_IP:8080"
echo "View logs: ./scripts/bot.sh logs"
echo "Stop bot:  ./scripts/bot.sh stop"
