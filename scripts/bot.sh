#!/bin/bash
# Control Kalshi Market Maker on DigitalOcean

DROPLET_IP="159.203.108.164"
DROPLET_USER="root"
REMOTE_DIR="/opt/kalshi-market-maker"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

run_ssh() {
    ssh $SSH_OPTS $DROPLET_USER@$DROPLET_IP "$1"
}

case "$1" in
    start)
        echo "Starting bot..."
        run_ssh "cd $REMOTE_DIR && docker compose up -d"
        echo "Bot started! Dashboard: http://$DROPLET_IP:8080"
        ;;
    stop)
        echo "Stopping bot..."
        run_ssh "cd $REMOTE_DIR && docker compose down"
        echo "Bot stopped."
        ;;
    restart)
        echo "Restarting bot..."
        run_ssh "docker restart kalshi-market-maker"
        echo "Bot restarted!"
        ;;
    status)
        echo "=== Bot Status ==="
        run_ssh "docker ps --filter name=kalshi --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
        ;;
    logs)
        echo "=== Bot Logs (Ctrl+C to exit) ==="
        ssh $SSH_OPTS $DROPLET_USER@$DROPLET_IP "docker logs -f kalshi-market-maker"
        ;;
    logs-tail)
        echo "=== Last 50 log lines ==="
        run_ssh "docker logs --tail 50 kalshi-market-maker"
        ;;
    ssh)
        echo "Connecting to droplet..."
        ssh $SSH_OPTS $DROPLET_USER@$DROPLET_IP
        ;;
    *)
        echo "Kalshi Market Maker Control"
        echo ""
        echo "Usage: $0 {command}"
        echo ""
        echo "Commands:"
        echo "  start      Start the bot"
        echo "  stop       Stop the bot (EMERGENCY STOP)"
        echo "  restart    Restart the bot"
        echo "  status     Check if bot is running"
        echo "  logs       Stream live logs (Ctrl+C to exit)"
        echo "  logs-tail  Show last 50 log lines"
        echo "  ssh        SSH into the droplet"
        echo ""
        echo "Dashboard: http://$DROPLET_IP:8080"
        ;;
esac
