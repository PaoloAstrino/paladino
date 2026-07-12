#!/usr/bin/env bash
# =============================================================================
# Paladino Quickstart Script (Unix/Linux/Mac)
# Automates first-time setup: Docker, Neo4j, schema initialization, sample data
#
# Usage: ./scripts/quickstart.sh
# Make executable: chmod +x scripts/quickstart.sh
# =============================================================================

set -euo pipefail

# --- ANSI Colors ---
GREEN='\033[0;92m'
YELLOW='\033[0;93m'
RED='\033[0;91m'
CYAN='\033[0;96m'
BOLD='\033[1m'
RESET='\033[0m'

# --- Project root (resolve to absolute path) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

# --- Load .env variables if they exist ---
if [[ -f .env ]]; then
    # Source only variables we need (avoid polluting environment)
    NEO4J_PASSWORD=$(grep -E "^NEO4J_PASSWORD=" .env 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "CHANGE_ME_IN_PRODUCTION")
    API_KEYS=$(grep -E "^API_KEYS=" .env 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")
else
    NEO4J_PASSWORD="CHANGE_ME_IN_PRODUCTION"
    API_KEYS=""
fi

echo ""
echo -e "${BOLD}${CYAN}=============================================${RESET}"
echo -e "${BOLD}${CYAN}  Paladino Quickstart - Unix/Linux/Mac${RESET}"
echo -e "${BOLD}${CYAN}  Italian Public Funds Knowledge Graph${RESET}"
echo -e "${BOLD}${CYAN}=============================================${RESET}"
echo ""

# =============================================================================
# Step 1: Check Docker
# =============================================================================
echo -e "${CYAN}[1/5] Checking Docker...${RESET}"

if ! docker info &>/dev/null; then
    echo -e "${RED}ERROR: Docker is not running.${RESET}"
    echo ""
    echo "Please start Docker and try again."
    echo "  - Docker Desktop: Open from Applications/Activities"
    echo "  - Linux (systemd): sudo systemctl start docker"
    echo "  - Then re-run: ./scripts/quickstart.sh"
    echo ""
    exit 1
fi
echo -e "${GREEN}  Docker is running.${RESET}"

# =============================================================================
# Step 2: Start Neo4j
# =============================================================================
echo -e "${CYAN}[2/5] Starting Neo4j...${RESET}"

# Check if Neo4j container is already running
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qi "paladino-neo4j"; then
    echo -e "${YELLOW}  Neo4j is already running. Skipping start.${RESET}"
else
    # Check if container exists but is stopped
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qi "paladino-neo4j"; then
        echo -e "${YELLOW}  Neo4j container exists but is stopped. Starting...${RESET}"
    else
        echo "  Pulling images and starting Neo4j..."
    fi

    if ! docker compose up -d 2>&1; then
        # Fallback to docker-compose (v1)
        if ! docker-compose up -d 2>&1; then
            echo -e "${RED}ERROR: Failed to start Neo4j.${RESET}"
            echo "Please check docker-compose.yml and your Docker installation."
            exit 1
        fi
    fi
    echo -e "${GREEN}  Neo4j container started.${RESET}"
fi

# =============================================================================
# Step 3: Wait for Neo4j to be ready
# =============================================================================
echo -e "${CYAN}[3/5] Waiting for Neo4j to be ready...${RESET}"

MAX_WAIT=60
WAITED=0

while [[ ${WAITED} -lt ${MAX_WAIT} ]]; do
    # Try cypher-shell inside container first
    if docker exec paladino-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" "RETURN 1" &>/dev/null; then
        echo -e "${GREEN}  Neo4j is ready (${WAITED}s).${RESET}"
        break
    fi

    # Fallback: check if Bolt port is open
    if command -v nc &>/dev/null; then
        if nc -z localhost 7687 &>/dev/null; then
            # Port is open, give it a moment to fully initialize
            sleep 2
            echo -e "${GREEN}  Neo4j is ready (${WAITED}s).${RESET}"
            break
        fi
    fi

    # Fallback: use bash /dev/tcp (if available)
    if (echo > /dev/tcp/localhost/7687) &>/dev/null; then
        sleep 2
        echo -e "${GREEN}  Neo4j is ready (${WAITED}s).${RESET}"
        break
    fi

    sleep 2
    WAITED=$((WAITED + 2))
    echo -n "."
done
echo ""

if [[ ${WAITED} -ge ${MAX_WAIT} ]]; then
    echo -e "${RED}ERROR: Neo4j did not become ready within ${MAX_WAIT} seconds.${RESET}"
    echo ""
    echo "Check container logs for details:"
    echo "  docker logs paladino-neo4j"
    echo ""
    echo "Common issues:"
    echo "  - Not enough RAM (Neo4j requires at least 4GB available)"
    echo "  - Password not set correctly in .env (NEO4J_PASSWORD)"
    echo "  - Port 7687 already in use by another process"
    echo "    Check with: lsof -i :7687  (macOS/Linux)"
    echo ""
    exit 1
fi

# =============================================================================
# Step 4: Initialize schema
# =============================================================================
echo -e "${CYAN}[4/5] Initializing database schema...${RESET}"

if ! python scripts/etl/init_schema.py 2>&1; then
    echo -e "${RED}ERROR: Schema initialization failed.${RESET}"
    echo ""
    echo "Check the output above for details."
    echo "Common issues:"
    echo "  - Neo4j credentials in .env do not match NEO4J_AUTH in docker-compose.yml"
    echo "  - Neo4j is still starting up (wait a few more seconds and retry)"
    echo "  - Python dependencies not installed (run: pip install -e .)"
    exit 1
fi
echo -e "${GREEN}  Schema initialized successfully.${RESET}"

# =============================================================================
# Step 5: Load sample data
# =============================================================================
echo -e "${CYAN}[5/5] Loading sample data...${RESET}"

if paladino load-samples 2>&1; then
    echo -e "${GREEN}  Sample data loaded successfully.${RESET}"
else
    echo -e "${YELLOW}WARNING: Sample data loading encountered issues.${RESET}"
    echo "This is non-critical. You can load data later via the CLI."
fi

# =============================================================================
# Success message
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}=============================================${RESET}"
echo -e "${BOLD}${GREEN}  Setup Complete!${RESET}"
echo -e "${BOLD}${GREEN}=============================================${RESET}"
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo -e " 1. Start the API server:"
echo -e "    ${CYAN}paladino work --port 8000${RESET}"
echo ""
echo -e " 2. Open interactive docs in your browser:"
echo -e "    ${CYAN}http://localhost:8000/docs${RESET}"
echo ""
echo -e " 3. Launch the Investigator shell:"
echo -e "    ${CYAN}paladino investigate${RESET}"
echo ""

# Show API key from .env
if [[ -n "${API_KEYS}" ]]; then
    echo -e "${BOLD}Your API Key:${RESET}"
    echo -e "    ${CYAN}${API_KEYS}${RESET}"
    echo ""
    echo "  Use it in the X-API-Key header for API requests."
    echo ""
else
    echo -e "${YELLOW}NOTE: No API key found in .env. Set API_KEYS=your_key in .env to enable API authentication.${RESET}"
    echo ""
fi

echo -e "${BOLD}This script is idempotent -- safe to re-run at any time.${RESET}"
echo ""
