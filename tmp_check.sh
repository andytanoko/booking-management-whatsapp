#!/bin/bash
LOG=/tmp/compose-up.log
cd ~/booking-management-whatsapp

# Kill any stuck compose/podman processes from previous attempts
pkill -f 'docker-compose\|docker compose\|podman.*build' 2>/dev/null || true
sleep 1

# Reset podman socket
rm -f /run/user/1000/podman/podman.sock 2>/dev/null || true
systemctl --user reset-failed 2>/dev/null || true
systemctl --user restart podman.socket 2>/dev/null || true
sleep 2

# Launch compose build in background, survives SSH exit
nohup bash -c 'DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose up --build -d' > $LOG 2>&1 &
BG_PID=$!
echo "Build launched as PID $BG_PID"
echo "Tail log: tail -f $LOG"

# Wait a few seconds and confirm it started
sleep 5
if kill -0 $BG_PID 2>/dev/null; then
  echo "Build is running (PID $BG_PID)"
else
  echo "Build process ended early — check $LOG"
fi

# Show whatever output has appeared so far
cat $LOG
