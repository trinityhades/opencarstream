#!/bin/bash

# Colors for nice output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_TEMPLATE="$SCRIPT_DIR/com.opencarstream.server.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/com.opencarstream.server.plist"
LOG_FILE="$SCRIPT_DIR/server.log"

usage() {
    echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
    echo
    echo "Actions:"
    echo "  install    - Configures and installs the launchd background service"
    echo "  uninstall  - Uninstalls and removes the launchd background service"
    echo "  start      - Starts the background service"
    echo "  stop       - Stops the background service"
    echo "  restart    - Restarts the background service"
    echo "  status     - Checks the status of the service in launchd"
    echo "  logs       - Follows the service stdout/stderr logs"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

case "$1" in
    install)
        echo -e "${BLUE}Installing launchd service...${NC}"
        if [ ! -f "$PLIST_TEMPLATE" ]; then
            echo -e "${RED}Error: Template file $PLIST_TEMPLATE not found!${NC}"
            exit 1
        fi

        # Create LaunchAgents directory if it doesn't exist
        mkdir -p "$HOME/Library/LaunchAgents"

        # Replace placeholder and copy
        sed "s|{{REPO_PATH}}|$SCRIPT_DIR|g" "$PLIST_TEMPLATE" > "$PLIST_DEST"
        echo -e "${GREEN}Configuration written to: $PLIST_DEST${NC}"

        # Load the service
        echo "Loading service in launchd..."
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
        launchctl load "$PLIST_DEST"
        
        echo -e "${GREEN}OpenCarStream service installed and started successfully!${NC}"
        echo -e "Access it at: http://localhost:33333"
        ;;

    uninstall)
        echo -e "${BLUE}Uninstalling launchd service...${NC}"
        if [ -f "$PLIST_DEST" ]; then
            launchctl unload "$PLIST_DEST" 2>/dev/null || true
            rm -f "$PLIST_DEST"
            echo -e "${GREEN}Successfully uninstalled and removed $PLIST_DEST${NC}"
        else
            echo -e "Service plist not found at $PLIST_DEST, nothing to uninstall."
        fi
        ;;

    start)
        echo -e "${BLUE}Starting service...${NC}"
        launchctl start com.opencarstream.server
        echo -e "${GREEN}Start command sent.${NC}"
        ;;

    stop)
        echo -e "${BLUE}Stopping service...${NC}"
        launchctl stop com.opencarstream.server
        echo -e "${GREEN}Stop command sent.${NC}"
        ;;

    restart)
        echo -e "${BLUE}Restarting service...${NC}"
        launchctl stop com.opencarstream.server 2>/dev/null || true
        launchctl start com.opencarstream.server
        echo -e "${GREEN}Restart command sent.${NC}"
        ;;

    status)
        echo -e "${BLUE}Checking service status...${NC}"
        STATUS=$(launchctl list | grep com.opencarstream.server || true)
        if [ -n "$STATUS" ]; then
            echo -e "${GREEN}Service is registered in launchd:${NC}"
            echo "$STATUS"
            # Extract PID from launchctl list output (first column)
            PID=$(echo "$STATUS" | awk '{print $1}')
            if [ "$PID" != "-" ] && [ -n "$PID" ]; then
                echo -e "Running with PID: $PID"
                if command -v ps >/dev/null; then
                    ps -p "$PID" -o %cpu,%mem,comm | tail -n 1
                fi
            else
                echo -e "${RED}Service is registered but currently NOT running.${NC}"
            fi
        else
            echo -e "${RED}Service is NOT loaded in launchd.${NC}"
        fi
        ;;

    logs)
        echo -e "${BLUE}Tailing logs at $LOG_FILE... (Ctrl+C to exit)${NC}"
        if [ ! -f "$LOG_FILE" ]; then
            touch "$LOG_FILE"
        fi
        tail -n 100 -f "$LOG_FILE"
        ;;

    *)
        usage
        ;;
esac
