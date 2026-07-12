# Risk Score History Tracking Guide

**Tier 2 Foundation Feature** | Paladino v0.2.0+

This guide explains how to use Paladino's Risk Score History Tracking feature to monitor how company risk profiles evolve over time, identify sudden risk spikes, and analyze risk distribution across sectors.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Risk Tier Classification](#risk-tier-classification)
- [API Endpoints](#api-endpoints)
- [Usage Examples](#usage-examples)
- [Trend Analysis](#trend-analysis)
- [Dashboard Queries](#dashboard-queries)
- [Alert Triggers](#alert-triggers)
- [Best Practices](#best-practices)

---

## Overview

The Risk Score History Tracking feature enables analysts to:

1. **Track risk evolution** - See how a company's risk score changes over time
2. **Identify sudden spikes** - Detect companies with rapid risk increases (>0.3 delta)
3. **Compare across sectors** - Analyze risk distribution by industry (ATECO codes)
4. **Monitor tier crossings** - Get alerts when companies cross risk boundaries (e.g., Medium → High)

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Snapshot** | A point-in-time record of a company's risk score, stored as a `Version` node |
| **Trend Analysis** | Statistical analysis of risk evolution (delta, direction, volatility) |
| **Risk Tier** | Classification: HIGH (≥0.7), MEDIUM (0.4-0.69), LOW (<0.4) |
| **Tier Crossing** | When a company moves between risk tiers |
| **Critical Alert** | Risk increase >0.3 in a single period |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Risk Analysis Pipeline                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  RiskEngine.run_global_analysis()                               │
│    │                                                             │
│    ├──► Calculate risk scores for all companies                 │
│    │    - Single-bidder ratio (weight: 0.4)                     │
│    │    - Market dominance via PageRank (weight: 0.3)           │
│    │    - Buyer concentration (weight: 0.3)                     │
│    │    - Fraud pattern library (10 detectors)                  │
│    │                                                             │
│    └──► save_all_risk_snapshots()                               │
│         │                                                        │
│         └──► Create Version nodes linked via HAS_VERSION        │
│                                                                  │
│  TemporalAnalyzer                                                │
│    ├──► get_risk_score_history()    - Timeline of snapshots     │
│    ├──► get_risk_trend_analysis()   - Delta, direction, vol     │
│    ├──► get_risk_distribution_over_time() - Global stats        │
│    └──► get_companies_with_risk_changes() - Biggest movers      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Model

**Version Node (Risk Snapshot)**
```cypher
(:Version {
  id:             "snap-uuid-123",
  entityId:       "company-uuid-456",
  risk_score:     0.75,
  change_date:    datetime("2024-01-15T10:30:00Z"),
  snapshot_type:  "risk_score",
  anomaly_flags:  ["high_single_bidder_ratio", "market_dominance_high"]
})
```

**Relationship**
```cypher
(:Company)-[:HAS_VERSION]->(:Version {snapshot_type: 'risk_score'})
```

---

## Risk Tier Classification

Risk scores are classified into three tiers:

| Tier | Score Range | Badge Color | Description |
|------|-------------|-------------|-------------|
| **HIGH** | ≥ 0.70 | 🔴 Red | Elevated fraud risk, requires immediate attention |
| **MEDIUM** | 0.40 - 0.69 | 🟡 Yellow | Moderate risk, monitor closely |
| **LOW** | < 0.40 | 🟢 Green | Low risk, routine monitoring |

### Tier Boundaries

Crossing a tier boundary is a significant event that triggers alerts:

```python
from paladino.models import RiskTier

# Classify a score
tier = RiskTier.from_score(0.75)  # Returns RiskTier.HIGH

# Check for tier crossing
old_tier = RiskTier.from_score(0.65)  # MEDIUM
new_tier = RiskTier.from_score(0.75)  # HIGH
tier_crossed = old_tier != new_tier  # True
```

---

## API Endpoints

### 1. Get Company Risk History

```http
GET /companies/{company_id}/risk-history
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `company_id` | path | required | Company node ID (UUID) |
| `snapshots` | query | 8 | Number of snapshots (1-50) |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/companies/uuid-123/risk-history?snapshots=10" \
  -H "X-API-Key: your-api-key"
```

**Example Response:**
```json
{
  "company_id": "uuid-123",
  "company_name": "ACME Costruzioni SRL",
  "current_risk_score": 0.75,
  "current_risk_tier": "high",
  "snapshots": [
    {
      "company_id": "uuid-123",
      "company_name": "ACME Costruzioni SRL",
      "risk_score": 0.75,
      "risk_tier": "high",
      "change_date": "2024-01-15T10:30:00Z",
      "anomaly_flags": ["high_single_bidder_ratio"]
    },
    {
      "company_id": "uuid-123",
      "company_name": "ACME Costruzioni SRL",
      "risk_score": 0.62,
      "risk_tier": "medium",
      "change_date": "2023-10-15T10:30:00Z",
      "anomaly_flags": []
    }
  ],
  "snapshots_count": 2
}
```

---

### 2. Get Company Risk Trend

```http
GET /companies/{company_id}/risk-trend
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `company_id` | path | required | Company node ID (UUID) |
| `snapshots` | query | 8 | Number of snapshots to analyze (1-50) |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/companies/uuid-123/risk-trend" \
  -H "X-API-Key: your-api-key"
```

**Example Response:**
```json
{
  "company_id": "uuid-123",
  "company_name": "ACME Costruzioni SRL",
  "trend": {
    "company_id": "uuid-123",
    "company_name": "ACME Costruzioni SRL",
    "current_score": 0.75,
    "current_tier": "high",
    "previous_score": 0.45,
    "previous_tier": "medium",
    "delta": 0.30,
    "delta_percent": 66.67,
    "direction": "increasing",
    "volatility": 0.1523,
    "max_score": 0.75,
    "min_score": 0.45,
    "tier_crossed": true,
    "significant_increase": false,
    "snapshots_count": 4,
    "period_start": "2023-04-15T10:30:00Z",
    "period_end": "2024-01-15T10:30:00Z"
  },
  "snapshots": [...]
}
```

**Trend Metrics:**

| Metric | Description |
|--------|-------------|
| `delta` | Absolute change from oldest to newest snapshot |
| `delta_percent` | Percentage change (null if previous score is 0) |
| `direction` | "increasing" (>5%), "decreasing" (<-5%), or "stable" |
| `volatility` | Standard deviation of scores |
| `tier_crossed` | True if company moved between risk tiers |
| `significant_increase` | True if delta > 0.3 |

---

### 3. Get Risk Dashboard

```http
GET /risk/dashboard
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `quarters` | query | 8 | Number of past quarters (1-20) |
| `limit` | query | 20 | Max companies in change lists (1-100) |

**Example Request:**
```bash
curl -X GET "http://localhost:8000/risk/dashboard?quarters=12&limit=50" \
  -H "X-API-Key: your-api-key"
```

**Example Response:**
```json
{
  "generated_at": "2024-01-15T12:00:00Z",
  "total_companies": 5000,
  "companies_with_risk": 3500,
  "high_risk_count": 525,
  "medium_risk_count": 1225,
  "low_risk_count": 1750,
  "distribution_history": [
    {
      "period": "2023-Q3",
      "year": 2023,
      "quarter": 3,
      "high_risk_count": 480,
      "medium_risk_count": 1200,
      "low_risk_count": 1820,
      "total_companies": 3500,
      "avg_risk_score": 0.42,
      "median_risk_score": 0.38,
      "stddev_risk_score": 0.21,
      "high_risk_percent": 13.71,
      "medium_risk_percent": 34.29,
      "low_risk_percent": 52.0
    }
  ],
  "biggest_increases": [
    {
      "company_id": "uuid-456",
      "company_name": "Rossi SRL",
      "region": "Lombardia",
      "ateco": "64.99",
      "old_score": 0.35,
      "new_score": 0.75,
      "delta": 0.4,
      "old_tier": "low",
      "new_tier": "high",
      "tier_crossed": true,
      "change_type": "increase",
      "severity": "critical"
    }
  ],
  "biggest_decreases": [...],
  "critical_alerts": [...],
  "tier_crossings": [...]
}
```

---

## Usage Examples

### Example 1: Track Risk Evolution for a Specific Company

```python
from paladino.db import Neo4jConnection
from paladino.analytics.temporal_analytics import TemporalAnalyzer

conn = Neo4jConnection()
analyzer = TemporalAnalyzer(conn)

# Get risk history
company_id = "uuid-123"
history = analyzer.get_risk_score_history(company_id, snapshots=12)

print(f"Risk evolution for company {company_id}:")
for snapshot in reversed(history):  # Chronological order
    print(f"  {snapshot['change_date']}: {snapshot['risk_score']:.2f}")

conn.close()
```

**Output:**
```
Risk evolution for company uuid-123:
  2023-04-15: 0.45
  2023-07-15: 0.52
  2023-10-15: 0.62
  2024-01-15: 0.75
```

---

### Example 2: Identify Companies with Sudden Risk Spikes

```python
from paladino.db import Neo4jConnection
from paladino.analytics.temporal_analytics import TemporalAnalyzer

conn = Neo4jConnection()
analyzer = TemporalAnalyzer(conn)

# Get companies with significant risk changes
changes = analyzer.get_companies_with_risk_changes(limit=10, min_delta=0.2)

print("🚨 Critical Alerts (risk increase > 0.3):")
for alert in changes['critical_alerts']:
    print(f"  {alert['company_name']}: {alert['old_score']:.2f} → {alert['new_score']:.2f} (Δ{alert['delta']:.2f})")

print("\n📈 Biggest Increases:")
for item in changes['increases'][:5]:
    tier_change = f" [{item['old_tier']}→{item['new_tier']}]" if item['tier_crossed'] else ""
    print(f"  {item['company_name']}: {item['old_score']:.2f} → {item['new_score']:.2f}{tier_change}")

conn.close()
```

---

### Example 3: Analyze Risk Distribution Trends

```python
from paladino.db import Neo4jConnection
from paladino.analytics.temporal_analytics import TemporalAnalyzer

conn = Neo4jConnection()
analyzer = TemporalAnalyzer(conn)

# Get distribution over last 8 quarters
distribution = analyzer.get_risk_distribution_over_time(quarters=8)

print("Risk Distribution Over Time:")
print(f"{'Period':<10} {'High':>6} {'Medium':>8} {'Low':>6} {'Avg':>6}")
print("-" * 40)

for period in distribution:
    print(f"{period['period']:<10} {period['high_risk_count']:>6} "
          f"{period['medium_risk_count']:>8} {period['low_risk_count']:>6} "
          f"{period['avg_risk_score']:>6.2f}")

conn.close()
```

**Output:**
```
Risk Distribution Over Time:
Period         High   Medium    Low    Avg
----------------------------------------
2022-Q3          450     1100   1950   0.38
2022-Q4          465     1150   1885   0.39
2023-Q1          480     1200   1820   0.40
2023-Q2          495     1225   1780   0.41
2023-Q3          510     1250   1740   0.42
2023-Q4          525     1275   1700   0.43
```

---

### Example 4: Get Comprehensive Trend Analysis

```python
from paladino.db import Neo4jConnection
from paladino.analytics.temporal_analytics import TemporalAnalyzer

conn = Neo4jConnection()
analyzer = TemporalAnalyzer(conn)

company_id = "uuid-123"
trend = analyzer.get_risk_trend_analysis(company_id, snapshots=8)

print(f"Risk Trend Analysis for {trend['company_name']}:")
print(f"  Current Score: {trend['current_score']:.2f} ({trend['current_tier']})")
print(f"  Previous Score: {trend['previous_score']:.2f} ({trend['previous_tier']})")
print(f"  Delta: {trend['delta']:+.2f} ({trend['delta_percent']:+.1f}%)")
print(f"  Direction: {trend['direction']}")
print(f"  Volatility: {trend['volatility']:.4f}")
print(f"  Range: [{trend['min_score']:.2f}, {trend['max_score']:.2f}]")
print(f"  Tier Crossed: {'Yes ⚠️' if trend['tier_crossed'] else 'No'}")
print(f"  Significant Increase: {'Yes 🚨' if trend['significant_increase'] else 'No'}")

conn.close()
```

---

## Trend Analysis

### Direction Calculation

The trend direction is determined by the delta (change from oldest to newest snapshot):

| Delta Range | Direction |
|-------------|-----------|
| > +0.05 | increasing |
| < -0.05 | decreasing |
| -0.05 to +0.05 | stable |

### Volatility Interpretation

Volatility (standard deviation) indicates how much the risk score fluctuates:

| Volatility | Interpretation |
|------------|----------------|
| < 0.05 | Very stable, consistent risk profile |
| 0.05 - 0.15 | Moderate fluctuation |
| > 0.15 | High volatility, unpredictable risk pattern |

### Alert Conditions

| Condition | Threshold | Action |
|-----------|-----------|--------|
| **Significant Increase** | delta > 0.3 | Flag for immediate review |
| **Tier Crossing** | old_tier ≠ new_tier | Generate alert |
| **Critical Alert** | delta > 0.3 AND direction = increasing | Escalate to senior analyst |

---

## Dashboard Queries

### Query 1: Current Risk Distribution

```cypher
MATCH (c:Company)
WITH count(c) AS total,
     count(CASE WHEN c.risk_score >= 0.7 THEN c END) AS high,
     count(CASE WHEN c.risk_score >= 0.4 AND c.risk_score < 0.7 THEN c END) AS medium,
     count(CASE WHEN c.risk_score < 0.4 AND c.risk_score > 0 THEN c END) AS low
RETURN total, high, medium, low,
       round(toFloat(high)/total*100, 2) AS high_pct,
       round(toFloat(medium)/total*100, 2) AS medium_pct,
       round(toFloat(low)/total*100, 2) AS low_pct
```

### Query 2: Companies with Risk Increase > 0.3

```cypher
MATCH (c:Company)-[:HAS_VERSION]->(v:Version)
WHERE v.risk_score IS NOT NULL
WITH c, v
ORDER BY v.change_date DESC
WITH c, collect(v) AS versions
WHERE size(versions) >= 2
WITH c,
     versions[0].risk_score AS new_score,
     versions[1].risk_score AS old_score
WHERE (new_score - old_score) > 0.3
RETURN c.nome_normalizzato AS company,
       old_score,
       new_score,
       (new_score - old_score) AS delta
ORDER BY delta DESC
LIMIT 20
```

### Query 3: Risk Trend by Sector (ATECO)

```cypher
MATCH (c:Company)-[:HAS_VERSION]->(v:Version)
WHERE v.risk_score IS NOT NULL
  AND c.ateco IS NOT NULL
WITH c.ateco AS sector, v.risk_score AS score
WITH sector, collect(score) AS scores
RETURN sector,
       avg(toFloat(scores)) AS avg_risk,
       count(CASE WHEN scores[0] >= 0.7 THEN 1 END) AS high_risk_count,
       count(scores) AS total_companies
ORDER BY avg_risk DESC
LIMIT 10
```

---

## Alert Triggers

### Configuring Alerts

The system automatically flags the following conditions:

1. **Risk Increased by > 0.3**
   - Indicates sudden deterioration in risk profile
   - May signal new fraudulent activity or pattern detection

2. **Tier Boundary Crossing**
   - LOW → MEDIUM: Company now requires closer monitoring
   - MEDIUM → HIGH: Immediate investigation recommended
   - HIGH → MEDIUM: Risk mitigation may be working

3. **Sustained Increase**
   - Three or more consecutive snapshots showing increase
   - Indicates systematic issues rather than one-off events

### Setting Up Monitoring

```python
def check_risk_alerts(company_id: str) -> list[str]:
    """Check for risk alerts for a company."""
    from paladino.db import Neo4jConnection
    from paladino.analytics.temporal_analytics import TemporalAnalyzer
    
    conn = Neo4jConnection()
    analyzer = TemporalAnalyzer(conn)
    
    alerts = []
    trend = analyzer.get_risk_trend_analysis(company_id)
    
    if trend['significant_increase']:
        alerts.append(f"🚨 CRITICAL: Risk increased by {trend['delta']:.2f}")
    
    if trend['tier_crossed']:
        alerts.append(f"⚠️ ALERT: Tier crossed from {trend['previous_tier']} to {trend['current_tier']}")
    
    if trend['volatility'] > 0.15:
        alerts.append(f"⚡ WARNING: High volatility ({trend['volatility']:.2f})")
    
    conn.close()
    return alerts
```

---

## Best Practices

### 1. Run Risk Analysis Regularly

Schedule `RiskEngine.run_global_analysis()` to run periodically:

```python
from paladino.db import Neo4jConnection
from paladino.analytics.risk_engine import RiskEngine

conn = Neo4jConnection()
engine = RiskEngine(conn)

# Run full analysis and save snapshots
engine.run_global_analysis()

conn.close()
```

**Recommended frequency:**
- **High-activity graphs**: Weekly
- **Standard graphs**: Monthly
- **Archive/stable graphs**: Quarterly

### 2. Monitor Dashboard Regularly

Check `/risk/dashboard` weekly to:
- Identify emerging risk patterns
- Track sector-level trends
- Prioritize investigations

### 3. Set Up Automated Alerts

Integrate with your monitoring system:

```python
# Pseudo-code for alert integration
dashboard = api.get_risk_dashboard()

for alert in dashboard['critical_alerts']:
    send_slack_alert(
        channel="#risk-alerts",
        message=f"🚨 {alert['company_name']}: Risk increased by {alert['delta']:.2f}"
    )
```

### 4. Investigate Tier Crossings

When a company crosses a tier boundary:
1. Review the fraud pattern evidence
2. Check recent tender activity
3. Compare with sector peers
4. Document findings in comments

### 5. Use Trend Analysis for Prioritization

| Trend Pattern | Priority | Action |
|---------------|----------|--------|
| Increasing + Tier Crossing | 🔴 High | Immediate investigation |
| Increasing + High Volatility | 🟡 Medium | Schedule review |
| Stable | 🟢 Low | Routine monitoring |
| Decreasing | 🟢 Low | Verify mitigation effectiveness |

---

## API Reference

### Response Models

#### RiskSnapshot
```json
{
  "company_id": "string",
  "company_name": "string | null",
  "risk_score": "float (0.0-1.0)",
  "risk_tier": "high | medium | low",
  "change_date": "datetime",
  "anomaly_flags": ["string"]
}
```

#### RiskTrendAnalysis
```json
{
  "company_id": "string",
  "company_name": "string | null",
  "current_score": "float",
  "current_tier": "string",
  "previous_score": "float | null",
  "previous_tier": "string | null",
  "delta": "float",
  "delta_percent": "float | null",
  "direction": "increasing | decreasing | stable",
  "volatility": "float",
  "max_score": "float",
  "min_score": "float",
  "tier_crossed": "boolean",
  "significant_increase": "boolean",
  "snapshots_count": "integer",
  "period_start": "datetime | null",
  "period_end": "datetime | null"
}
```

#### RiskDistribution
```json
{
  "period": "string (YYYY-QN)",
  "year": "integer",
  "quarter": "integer (1-4)",
  "high_risk_count": "integer",
  "medium_risk_count": "integer",
  "low_risk_count": "integer",
  "total_companies": "integer",
  "avg_risk_score": "float",
  "median_risk_score": "float",
  "stddev_risk_score": "float | null",
  "high_risk_percent": "float",
  "medium_risk_percent": "float",
  "low_risk_percent": "float"
}
```

---

## Troubleshooting

### No Risk History Available

**Problem:** `get_risk_score_history()` returns empty results.

**Solution:**
1. Ensure `RiskEngine.run_global_analysis()` has been executed
2. Verify `save_all_risk_snapshots()` was called after analysis
3. Check that the company has `risk_score > 0`

### Dates Not Migrated

**Problem:** Temporal queries return empty with date warning.

**Solution:**
```bash
python scripts/migrate_date_types.py
```

### High Volatility Scores

**Problem:** Volatility seems unusually high.

**Possible causes:**
- Recent fraud pattern additions causing score jumps
- Data quality issues in source data
- Legitimate changes in company behavior

**Action:** Review individual snapshots to identify the cause.

---

## Related Documentation

- [Risk Engine](../reference/risk_engine.md) - Risk scoring methodology
- [Fraud Patterns](../reference/fraud_patterns.md) - 10 automated fraud detectors
- [Temporal Analytics](../reference/temporal_analytics.md) - Time-series analysis
- [Schema Documentation](../SCHEMA.md) - Graph schema reference
