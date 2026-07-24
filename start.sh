#!/bin/bash
# ── Alpha Intelligence — One-Click Launcher ──
# Starts ALL 3 servers: Backend API, Paper Trading, and Next.js Frontend
# Usage: ./start.sh
#cd ~/Documents/Alpha\ model && ./start.sh command to start website
echo ""
echo "🚀 ╔══════════════════════════════════════════════╗"
echo "   ║   Alpha Intelligence — Full Stack Launcher   ║"
echo "   ╚══════════════════════════════════════════════╝"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# ── Kill any stale processes on our ports ──
echo "🧹 Cleaning up stale processes..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:8001 | xargs kill -9 2>/dev/null
lsof -ti:8002 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null
sleep 1

# ── 1. Start Backend API (port 8000) ──
echo "📡 [1/3] Starting Backend API on http://localhost:8000..."
/usr/local/bin/python3 "$PROJECT_DIR/server.py" &
PID_BACKEND=$!
sleep 2

# ── 2. Start Paper Trading Engine (port 8001) ──
echo "📊 [2/3] Starting Paper Trading Engine on http://localhost:8001..."
/usr/local/bin/python3 "$PROJECT_DIR/paper_trading.py" &
PID_PAPER=$!
sleep 2

# ── 3. Start Next.js Frontend (port 3000) ──
echo "🖥️  [3/3] Starting Next.js Frontend on http://localhost:3000..."
cd "$PROJECT_DIR/frontend"
npx next dev --port 3000 &
PID_FRONTEND=$!
sleep 3

echo ""
echo "✅ ╔══════════════════════════════════════════════╗"
echo "   ║          All Systems Online                  ║"
echo "   ╠══════════════════════════════════════════════╣"
echo "   ║  🖥️  Frontend     → http://localhost:3000    ║"
echo "   ║  📡 Backend API  → http://localhost:8000    ║"
echo "   ║  📊 Paper Trade  → http://localhost:8001    ║"
echo "   ╚══════════════════════════════════════════════╝"
echo ""
echo "   Press Ctrl+C to stop all servers."
echo ""

# ── Open browser automatically ──
open "http://localhost:3000" 2>/dev/null

# ── Trap Ctrl+C to kill all ──
cleanup() {
    echo ""
    echo "🛑 Shutting down all servers..."
    kill $PID_BACKEND $PID_PAPER $PID_FRONTEND 2>/dev/null
    # Also make sure ports are freed
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    lsof -ti:8001 | xargs kill -9 2>/dev/null
    lsof -ti:3000 | xargs kill -9 2>/dev/null
    echo "✅ All servers stopped. Goodbye!"
    exit 0
}

trap cleanup SIGINT SIGTERM

wait
