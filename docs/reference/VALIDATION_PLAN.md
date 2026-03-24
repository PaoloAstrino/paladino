# 🧪 Paladino Validation Plan

## How to Verify Paladino Works and Delivers Value

This document provides a step-by-step validation plan to ensure Paladino functions correctly and delivers tangible value for analyzing Italian public spending data.

---

## 📋 Validation Pyramid

```
         ╱╲
        ╱  ╲      Level 4: Business Value
       ╱────╲     "Can I answer real questions?"
      ╱      ╲
     ╱────────╲   Level 3: Integration
    ╱          ╲   "Do all components work together?"
   ╱────────────╲
  ╱              ╲ Level 2: Data Pipeline
 ╱────────────────╲ "Does ETL load real data?"
╱                  ╲
╱────────────────────╲ Level 1: Unit Tests
                       "Does each function work?"
```

---

## Level 1: Unit Tests ✅ (Already Complete)

**Status:** 85/85 tests passing

```bash
cd paladino
pytest tests/unit/ -v
```

**What this validates:**
- Each function works in isolation
- Data models validate correctly
- Transformations produce expected outputs
- No syntax or import errors

**Confidence:** 30% - Necessary but not sufficient

---

## Level 2: Data Pipeline Validation

### Step 1: Start Infrastructure

```bash
# Start Neo4j
docker-compose up -d

# Verify Neo4j is running
docker-compose ps

# Check Neo4j logs
docker-compose logs neo4j

# Access Neo4j Browser
open http://localhost:7474
# Login: neo4j / your_password
```

**Expected:** Neo4j container running, browser accessible

---

### Step 2: Initialize Schema

```bash
cd paladino
python scripts/init_schema.py
```

**Expected Output:**
```
✓ Constraints created (X constraints)
✓ Indexes created (Y indexes)
✓ Vector indices created
✓ Schema version: 1
```

**Verification Query** (run in Neo4j Browser):
```cypher
SHOW CONSTRAINTS;
SHOW INDEXES;
```

**Expected:** 10+ constraints, 15+ indexes

---

### Step 3: Load Sample Data

#### Option A: Use Test Data (Recommended for Validation)

```bash
# Download sample OCDS data (ANAC)
python scripts/run_anac_etl.py --sample

# Verify data loaded
python -c "
from paladino.db import get_driver
driver = get_driver()
with driver.session() as session:
    result = session.run('MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC')
    for record in result:
        print(f'{record[\"label\"]}: {record[\"count\"]} nodes')
"
```

**Expected Output:**
```
Tender: 500 nodes
Company: 200 nodes
Buyer: 50 nodes
WINS relationships: 400 relationships
```

#### Option B: Load Your Own Data

```bash
# Configure data sources in .env
# ANAC_API_URL=https://dati.anticorruzione.it/opendata/ocds

# Run full ETL
python scripts/run_anac_etl.py
python scripts/run_opencup_etl.py
python scripts/run_istat_etl.py
```

---

### Step 4: Verify Data Quality

```bash
python scripts/validate_data.py
```

**Create this validation script:**

```python
# scripts/validate_data.py
from paladino.db import get_driver

def validate_data():
    driver = get_driver()
    
    checks = {
        "Companies have CF": "MATCH (c:Company) WHERE c.cf IS NOT NULL RETURN count(c) > 0 as passed",
        "Tenders have CIG": "MATCH (t:Tender) WHERE t.cig IS NOT NULL RETURN count(t) > 0 as passed",
        "Tenders have amounts": "MATCH (t:Tender) WHERE t.importo IS NOT NULL RETURN count(t) > 0 as passed",
        "WINS relationships exist": "MATCH ()-[r:WINS]->() RETURN count(r) > 0 as passed",
        "Companies located in regions": "MATCH (c:Company)-[:LOCATED_IN]->() RETURN count(c) > 0 as passed",
    }
    
    with driver.session() as session:
        for check_name, query in checks.items():
            result = session.run(query).single()
            passed = result["passed"] if result else False
            status = "✅" if passed else "❌"
            print(f"{status} {check_name}: {'PASS' if passed else 'FAIL'}")

if __name__ == "__main__":
    validate_data()
```

**Expected:** All checks pass ✅

---

## Level 3: Integration Validation

### Step 1: Test API Endpoints

```bash
# Start API server
paladino work --port 8000

# In another terminal, test endpoints:

# Health check
curl http://localhost:8000/health

# List templates
curl http://localhost:8000/templates

# Get company by CF
curl http://localhost:8000/companies/TEST123

# Graph statistics
curl http://localhost:8000/stats
```

**Expected:** JSON responses with data

---

### Step 2: Test CLI Commands

```bash
# Launch interactive mode
paladino

# Test stats command
paladino stats

# Test investigator (interactive)
paladino investigate
```

**In Investigator REPL, try:**
```
> templates
> Show me all companies
> Show tenders by amount
> q  # quit
```

---

### Step 3: Test GraphRAG Agent

```bash
# Natural language query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me the top 10 companies by number of tenders won", "limit": 10}'
```

**Expected:** Structured response with results

---

## Level 4: Business Value Validation

### Real Questions Paladino Should Answer

Create a validation questionnaire with **actual business questions**:

```python
# scripts/validation_questions.py
QUESTIONS = [
    # Basic Queries
    "Quante gare ci sono nel database?",
    "Quali sono le aziende con più gare aggiudicate?",
    "Qual è l'importo totale delle gare?",
    
    # Multi-hop Reasoning
    "Quali aziende hanno vinto gare in più regioni?",
    "Mostrami le gare collegate a progetti PNRR",
    "Quali buyer hanno emesso più gare?",
    
    # Risk Analysis
    "Quali sono le aziende a più alto rischio?",
    "Mostrami le gare con un solo offerente",
    "Quali aziende hanno un'alta concentrazione di buyer?",
    
    # Cross-Source Analysis
    "Quali progetti OpenCUP sono collegati a gare ANAC?",
    "Mostrami i progetti in regioni con declino demografico",
]

# Run each question through the GraphRAG agent
# Verify answers are meaningful and accurate
```

---

### Value Demonstration Checklist

| Capability | Test | Expected Result |
|------------|------|-----------------|
| **Data Integration** | Load ANAC + OpenCUP + ISTAT | All sources queryable together |
| **Cross-Source Queries** | "Gare collegate a progetti PNRR" | Returns linked data |
| **Risk Detection** | "Aziende ad alto rischio" | Returns companies with risk_score > 0.5 |
| **Semantic Search** | "Appalti pubblici in Lombardia" | Returns relevant results via vector search |
| **Multi-hop Reasoning** | "Aziende che vincono gare in regioni con declino" | Traverses Company→WINS→Tender→Location→Demographics |
| **Provenance** | "Da dove viene questo dato?" | Shows source, retrieval_date, confidence |

---

## 📊 Value Metrics

### Quantitative Metrics

Track these metrics to measure value:

| Metric | How to Measure | Target |
|--------|----------------|--------|
| **Data Coverage** | `MATCH (n) RETURN count(n)` | 10,000+ nodes |
| **Cross-Source Links** | `MATCH ()-[r:PART_OF_PROJECT]->() RETURN count(r)` | 1,000+ links |
| **Query Success Rate** | Successful queries / Total queries | >90% |
| **Query Latency** | Average response time | <2 seconds |
| **Risk Detection** | Companies with risk_score > 0.5 | Actionable alerts |

### Qualitative Value

Answer these questions:

1. **Can I answer questions that were previously impossible?**
   - Try: "Show me companies winning tenders in regions with demographic decline"
   - Before: Manual cross-referencing (hours)
   - After: Single query (seconds)

2. **Can I detect patterns that were previously hidden?**
   - Try: Risk analysis queries
   - Look for: Single-bidder ratios, buyer concentration

3. **Can I trace data provenance?**
   - Try: "Where did this company data come from?"
   - Expected: Source, dataset_version, retrieval_date

4. **Can non-technical users query the data?**
   - Try: Natural language queries via GraphRAG
   - Success: No Cypher knowledge required

---

## 🎯 Quick Validation Script

Create and run this comprehensive validation:

```python
# scripts/quick_validation.py
#!/usr/bin/env python3
"""
Quick validation script to verify Paladino is working.
Run this after setup to confirm everything functions.
"""

import sys
from pathlib import Path

def check_neo4j():
    """Verify Neo4j connection."""
    from paladino.db import get_driver
    try:
        driver = get_driver()
        with driver.session() as session:
            result = session.run("RETURN 1 as test").single()
            return result["test"] == 1
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
        return False

def check_data_loaded():
    """Verify data is loaded."""
    from paladino.db import get_driver
    driver = get_driver()
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN count(n) as count").single()
        count = result["count"]
        if count > 0:
            print(f"✅ Data loaded: {count} nodes")
            return True
        else:
            print("⚠️  No data loaded. Run ETL pipelines first.")
            return False

def check_api():
    """Verify API starts."""
    import requests
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ API responding")
            return True
        else:
            print(f"❌ API returned {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("⚠️  API not running. Start with: paladino work")
        return None  # Not a failure, just not running

def check_templates():
    """Verify query templates work."""
    from paladino.app.graphrag_agent import CypherQueryTemplates
    templates = CypherQueryTemplates()
    template_list = templates.list_templates()
    if len(template_list) > 5:
        print(f"✅ {len(template_list)} query templates available")
        return True
    return False

def main():
    print("🔍 Paladino Quick Validation\n")
    
    checks = [
        ("Neo4j Connection", check_neo4j),
        ("Data Loaded", check_data_loaded),
        ("API Running", check_api),
        ("Query Templates", check_templates),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\nChecking: {name}...")
        result = check_func()
        if result is None:
            results.append(("⚠️", name, "SKIPPED"))
        elif result:
            results.append(("✅", name, "PASS"))
        else:
            results.append(("❌", name, "FAIL"))
    
    print("\n\n" + "="*50)
    print("VALIDATION SUMMARY")
    print("="*50)
    
    for status, name, result in results:
        print(f"{status} {name}: {result}")
    
    passed = sum(1 for s, _, r in results if r == "PASS")
    total = len([r for r in results if r[2] != "SKIPPED"])
    
    print(f"\nResult: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 Paladino is working correctly!")
        return 0
    else:
        print("\n⚠️  Some checks failed. Review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

**Run it:**
```bash
python scripts/quick_validation.py
```

---

## 🏆 Value Demonstration Scenarios

### Scenario 1: Investigate a Company

```bash
paladino investigate
> Show me all tenders won by company CF ABC123
> What is their risk score?
> Show me their connections to other companies
```

**Value:** Instant corporate network analysis

---

### Scenario 2: Detect Risky Patterns

```bash
paladino investigate
> Show companies with high single-bidder ratio
> Which buyers work with these companies?
> Are there geographic patterns?
```

**Value:** Automated anomaly detection

---

### Scenario 3: Cross-Source Analysis

```bash
paladino investigate
> Link ANAC tenders to OpenCUP projects
> Show PNRR-funded projects in Southern Italy
> Which companies are involved?
```

**Value:** Multi-source intelligence impossible with manual analysis

---

## ✅ Validation Sign-Off

Before considering Paladino "working", confirm:

- [ ] Neo4j connection works
- [ ] Schema initialized (constraints + indexes)
- [ ] Sample data loaded (1000+ nodes minimum)
- [ ] API responds to health check
- [ ] CLI commands work (`paladino stats`, `paladino investigate`)
- [ ] At least 5 query templates return results
- [ ] Natural language query works
- [ ] Risk analysis returns meaningful scores
- [ ] Cross-source links exist (ANAC↔OpenCUP)
- [ ] Data provenance is tracked

**If all boxes checked:** ✅ Paladino is working and delivering value!

---

## 📞 Need Help?

If validation fails:
1. Check Neo4j is running: `docker-compose ps`
2. Check logs: `docker-compose logs neo4j`
3. Review `.env` configuration
4. Run unit tests: `pytest tests/unit/`
5. Check GitHub Issues for known problems

---

**Remember:** Value comes from **answering questions that were previously impossible or too time-consuming to answer**. Test Paladino with real questions from your domain!
