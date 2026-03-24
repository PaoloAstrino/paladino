"""
Paladino Constants
Shared constants and configuration for the Paladino ecosystem.
"""

from rich.theme import Theme

# ASCII Art Banner  (max ~50 chars wide — fits any 80-col terminal inside a Panel)
PALADIN_ART = (
    "\n"
    "  ____   _   _      _   ____  ___ _  _  ___  \n"
    " |  _ \ /_\ | |    /_\ |  _ \|_ _| \| |/ _ \ \n"
    " | |_) / _ \| |__ / _ \| |_) || || .`| || (_) |\n"
    " |  __/_/ \_\____/_/ \_\  __/|___|_|\_ |\___/ \n"
    " |_|                    |_|             \n"
    "\n"
    " ─────────────────────────────────────────────\n"
    "  🛡  Italian Public Funds Intelligence       \n"
    "  Neo4j · Graph AI · Fraud Detection          \n"
    " ─────────────────────────────────────────────\n"
)

# Rich Console Theme
PALADINO_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "brand": "bold magenta",
    "highlight": "bold yellow"
})

# CLI Configuration
CLI_TIMEOUT = 300  # 5 minutes for subprocess operations
DEFAULT_PORT = 8000
DEFAULT_HOST = "0.0.0.0"

# ETL Script Mappings
# Keys match `MaintenanceChoice.<X>.split(" (")[0]` to survive the CLI lookup.
ETL_SCRIPTS = {
    "Run ANAC ETL Pipeline":                  "run_anac_etl.py",
    "Run OpenCUP ETL Pipeline":               "run_opencup_etl.py",
    "Run ISTAT ETL Pipeline":                 "run_istat_etl.py",
    "Run Entity Resolution":                  "run_entity_resolution.py",
    "Run GDS Analytics":                      "run_gds_analytics.py",
    "Run Fraud Pattern Detection \U0001f534": "run_fraud_detection.py",
    "Run Supply Chain ETL \U0001f517":        "run_supply_chain_etl.py",
    "Run Temporal Analysis \U0001f4c8":       "run_temporal_analysis.py",
}

# ---------------------------------------------------------------------------
# Fraud Pattern Library - Thresholds & Registry
# ---------------------------------------------------------------------------

# Bid rotation: minimum occurrences of same winner group across buyers
FRAUD_BID_ROTATION_MIN_OCCURRENCES: int = 3
# Bid rotation: time window in days to look for rotation patterns
FRAUD_BID_ROTATION_WINDOW_DAYS: int = 365

# Split tendering: EU procurement simplified threshold (EUR)
# Tenders below this value can use negotiated procedure with no notice
FRAUD_SPLIT_TENDER_THRESHOLD_EUR: float = 40_000.0
# Split tendering: multiple tenders to same company within this window
FRAUD_SPLIT_TENDER_WINDOW_DAYS: int = 90
# Minimum number of split tenders to raise a flag
FRAUD_SPLIT_TENDER_MIN_COUNT: int = 3

# Short award window: days between publication and award decision
FRAUD_SHORT_AWARD_DAYS: int = 7

# Ghost bidding: companies that appear as participants but NEVER win
# across multiple tenders (provides artificial cover for real collusion)
FRAUD_GHOST_BIDDER_MIN_TENDERS: int = 5

# UBO conflict: maximum ownership chain depth to traverse
FRAUD_UBO_MAX_DEPTH: int = 5

# Abnormal pricing: z-score above this value is flagged
FRAUD_PRICE_ZSCORE_THRESHOLD: float = 2.5
# Minimum number of same-sector tenders to compute a reliable median
FRAUD_PRICE_MIN_SECTOR_SAMPLES: int = 5

# PNRR concentration: fraction of EU-funded wins considered suspicious
FRAUD_PNRR_CONCENTRATION_RATIO: float = 0.6
# Minimum PNRR wins to analyse concentration
FRAUD_PNRR_MIN_WINS: int = 3

# Community monopoly: fraction of community spend held by one company
FRAUD_COMMUNITY_MONOPOLY_RATIO: float = 0.7
# Minimum tenders in community to flag
FRAUD_COMMUNITY_MIN_TENDERS: int = 5

# Network clique: triangle count threshold to flag dense collusion ring
FRAUD_NETWORK_CLIQUE_TRIANGLE_THRESHOLD: int = 3

# Winner-loser ring: min co-appearances of same (winner,loser) pair
FRAUD_WINNER_LOSER_PAIR_MIN: int = 4

# Risk score contribution from FraudPatternLibrary (0.0 - 1.0)
# Added ON TOP of existing RiskEngine scores (capped at 1.0 globally)
FRAUD_PATTERN_RISK_CONTRIBUTION: dict = {
    "low":      0.05,
    "medium":   0.15,
    "high":     0.25,
    "critical": 0.40,
}

# ---------------------------------------------------------------------------
# Supply Chain & Ownership Graph - Thresholds
# ---------------------------------------------------------------------------

# Maximum hops to traverse in SUBCONTRACTS_TO / SUPPLIES_TO paths
SUPPLY_CHAIN_MAX_DEPTH: int = 4

# Maximum hops to traverse for beneficial-owner / SHAREHOLDER_OF chains
# (EU Anti-Money Laundering Directive uses 25% threshold, no depth limit)
OWNERSHIP_CHAIN_MAX_DEPTH: int = 10

# Minimum number of shared board members before flagging collusion risk
BOARD_OVERLAP_MIN_SHARED: int = 2

# A company that wins ≥ this many tenders but has ≤ SHELL_EMPLOYEE_THRESHOLD
# employees is a candidate shell company
SHELL_COMPANY_TENDER_WIN_MIN: int = 3
SHELL_COMPANY_EMPLOYEE_THRESHOLD: int = 5

# Enhanced shell detection — multi-factor model (ShellCompanyDetector)
# Weight applied to the VAT-registration gap signal
SHELL_VAT_ANOMALY_WEIGHT: float = 0.15

# Number of years without financial filings to trigger the dormancy signal
SHELL_DORMANCY_YEARS: int = 2

# Maximum number of boards a single director may sit on before triggering
# the board-concentration signal
SHELL_BOARD_CONCENTRATION_MAX: int = 20

# Shell score thresholds
# Companies above FLAG_THRESHOLD are classified HIGH_RISK
# Companies above ALERT_THRESHOLD (but below FLAG) are MEDIUM_RISK
SHELL_SCORE_FLAG_THRESHOLD: float = 0.50
SHELL_SCORE_ALERT_THRESHOLD: float = 0.35

# Carousel fraud: acceptable cycle length in the supply/subcontract graph
CAROUSEL_MIN_CYCLE_LENGTH: int = 3
CAROUSEL_MAX_CYCLE_LENGTH: int = 6

# Subcontractor concentration: if a winner routes > this fraction of its
# PNRR subcontracts to a single company it is flagged
SUBCONTRACTOR_CONCENTRATION_MAX: float = 0.8

# ETL entry for supply chain pipeline
SUPPLY_CHAIN_ETL_SCRIPT: str = "run_supply_chain_etl.py"

# ---------------------------------------------------------------------------
# Temporal Analysis
# ---------------------------------------------------------------------------

# Default number of quarters to look back for trend analysis
TEMPORAL_DEFAULT_QUARTERS: int = 8

# Spike detection: latest quarter is "suspicious" if it exceeds the rolling
# mean of prior quarters by this multiplier
TEMPORAL_SPIKE_THRESHOLD: float = 2.0

# Minimum number of tenders in a quarter-company bucket to include in trends
TEMPORAL_MIN_TENDERS_PER_BUCKET: int = 2

# How many years of seasonal data to aggregate
TEMPORAL_SEASONAL_YEARS: int = 3

# Canonical pattern names  (used as node properties in the graph)
FRAUD_PATTERN_NAMES: dict = {
    "bid_rotation":          "Bid Rotation",
    "ghost_bidding":         "Ghost Bidding",
    "split_tendering":       "Split Tendering (Frazionamento)",
    "short_award_window":    "Short Award Window",
    "price_manipulation":    "Price Manipulation",
    "ubo_conflict":          "UBO / Ownership Conflict",
    "winner_loser_ring":     "Winner-Loser Collusion Ring",
    "pnrr_concentration":    "PNRR Fund Concentration",
    "community_monopoly":           "Community Monopoly",
    "network_clique":               "Dense Collusion Network (Triangle)",
    "carousel_fraud":               "Carousel Fraud (Supply Chain Cycle)",
    "board_overlap_collusion":      "Board Overlap Collusion",
    "subcontractor_concentration":  "Subcontractor Concentration",
    "shell_company_network":         "Shell Company Network (Multi-Factor)",
}
