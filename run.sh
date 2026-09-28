#!/usr/bin/env bash
cd "$(dirname "$0")"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP=$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('10.255.255.255',1));print(s.getsockname()[0])" 2>/dev/null)
echo "Open on phones:"
echo "http://${IP:-localhost}:8000"
exec python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
