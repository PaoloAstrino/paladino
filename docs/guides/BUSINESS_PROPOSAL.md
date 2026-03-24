# 🛡️ Paladino - Italian Public Funds Intelligence Platform

## Executive Summary

**Paladino** is a knowledge graph platform that transforms Italian public spending data into actionable intelligence. It enables organizations to query fragmented public data using natural language, detect risk patterns, and generate comprehensive reports in seconds instead of days.

---

## 🎯 The Problem

Italian public data is **fragmented across multiple sources**:

- **ANAC** - Public procurement tenders (97,000+ tenders)
- **OpenCUP** - Funded projects (9.7M+ projects)
- **ISTAT** - Demographics and geographic data
- **Registro Imprese** - Company information

**Current challenges:**
- ❌ Manual cross-referencing takes hours or days
- ❌ Hidden relationships between entities remain undiscovered
- ❌ Risk patterns are difficult to detect at scale
- ❌ No unified view of public spending ecosystem
- ❌ Reporting requires manual data compilation

---

## 💡 The Paladino Solution

Paladino integrates all data sources into a **unified knowledge graph** with:

### 1. Natural Language Intelligence
Ask questions in plain Italian and get instant answers:
- *"Quali aziende hanno vinto più gare in Sicilia?"*
- *"Mostrami i progetti collegati a gare ANAC"*
- *"Quali buyer hanno emesso più gare?"*

### 2. Cross-Source Analysis
Automatically link related data:
- Tenders → Projects (2,166+ connections already mapped)
- Companies → Locations → Demographics
- Buyers → Tenders → Winners

### 3. Risk Detection
Automated anomaly detection:
- Single-bidder tender ratios
- Buyer concentration patterns
- Geographic anomalies
- Corporate network analysis

### 4. Export & Reporting
Share findings with stakeholders:
- Export to CSV/Excel for presentations
- Generate Markdown reports
- Save investigation sessions
- JSON export for integration

---

## 📊 Platform Statistics (Current Deployment)

| Metric | Value |
|--------|-------|
| **Total Nodes** | 18.7 million |
| **Projects** | 9.7M (OpenCUP) |
| **Tenders** | 97K (ANAC) |
| **Companies** | 49K |
| **Buyers** | 13K |
| **Relationships** | 7 types, millions of connections |
| **Cross-Source Links** | 2,166+ tender→project links |

---

## 💰 Business Value & ROI

### Time Savings

| Task | Before | After | Savings |
|------|--------|-------|---------|
| Company background check | 2-4 hours | 30 seconds | **99%** |
| Cross-source analysis | 1-2 days | 1 minute | **99.9%** |
| Risk pattern detection | Nearly impossible | Automatic | **100%** |
| Report generation | 3-4 hours | 1 click | **99%** |

### Use Case Examples

#### 🏦 **Banking & Finance**
**Scenario:** Due diligence before lending to a company

**Before:**
- Manual search across multiple databases
- Call public registries
- Review PDF documents
- **Time: 4-6 hours per company**

**With Paladino:**
```
PALADINO 🔍 > Show all tenders won by company CF XYZ
PALADINO 🔍 > What is their risk score?
PALADINO 🔍 > .export csv
```
- **Time: 2 minutes**
- **Export ready for credit committee**

---

#### 📰 **Investigative Journalism**
**Scenario:** Find suspicious procurement patterns

**Before:**
- FOIA requests
- Manual data collection
- Spreadsheet analysis
- **Time: Weeks**

**With Paladino:**
```
PALADINO 🔍 > Companies with >70% single-bidder wins
PALADINO 🔍 > Show their buyer relationships
PALADINO 🔍 > .report investigation_001
```
- **Time: 5 minutes**
- **Report ready for publication**

---

#### ⚖️ **Legal & Compliance**
**Scenario:** Anti-corruption due diligence

**Before:**
- Multiple database subscriptions
- Manual cross-referencing
- External consultants
- **Cost: €5,000-10,000 per investigation**

**With Paladino:**
```
PALADINO 🔍 > Show corporate network for company XYZ
PALADINO 🔍 > Detect high-risk patterns
PALADINO 🔍 > .save due diligence_session
```
- **Time: 10 minutes**
- **Cost: Internal only**

---

#### 🏢 **Management Consulting**
**Scenario:** Market analysis for client

**Before:**
- Purchase multiple datasets
- Manual data cleaning
- weeks of analyst time
- **Cost: €20,000+ per study**

**With Paladino:**
```
PALADINO 🔍 > Top 50 companies by region and sector
PALADINO 🔍 > Show market concentration
PALADINO 🔍 > .export csv market_analysis
```
- **Time: 30 minutes**
- **Data ready for client presentation**

---

## 🛠️ Technical Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Data Sources   │ ──► │  ETL Pipeline    │ ──► │  Neo4j      │
│  ANAC, OpenCUP  │     │  (Polars)        │     │  Graph DB   │
│  ISTAT, etc.    │     │                  │     │             │
└─────────────────┘     └──────────────────┘     └─────────────┘
                                                       │
                                                       ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Export/Report  │ ◄── │  GraphRAG Agent  │ ◄── │  Query      │
│  CSV, JSON, MD  │     │  (LLM-powered)   │     │  Interface  │
└─────────────────┘     └──────────────────┘     └─────────────┘
```

### Key Technologies
- **Graph Database:** Neo4j 5.16+
- **ETL:** Polars (high-performance data processing)
- **AI/ML:** GraphRAG with LLM integration
- **API:** FastAPI (REST endpoints)
- **CLI:** Interactive investigation terminal

---

## 🔐 Security & Compliance

- **Local-First:** Runs on-premises, no cloud dependency
- **Data Sovereignty:** All data stays within your infrastructure
- **Audit Trail:** Full provenance tracking for all queries
- **Access Control:** Role-based permissions (enterprise feature)
- **GDPR Compliant:** Public data only, no personal data processing

---

## 📦 Deployment Options

### Option 1: On-Premises (Recommended)
- Full control over data and infrastructure
- No external dependencies
- Complete data sovereignty

**Requirements:**
- Server with 16-32GB RAM
- Docker Desktop or Kubernetes
- Neo4j 5.16+

### Option 2: Private Cloud
- Deployed in your AWS/Azure/GCP
- Managed infrastructure
- Scalable resources

### Option 3: Hybrid
- Core graph on-premises
- Optional cloud backup
- API access for remote teams

---

## 🎓 Training & Onboarding

### Included in Deployment

1. **Setup & Configuration** (1 day)
   - Infrastructure setup
   - Data pipeline configuration
   - Initial data load

2. **User Training** (2 hours)
   - Natural language query training
   - Export and reporting features
   - Best practices

3. **Administrator Training** (4 hours)
   - ETL pipeline management
   - Performance tuning
   - Backup and maintenance

### Documentation Provided

- User manual (Italian/English)
- API documentation
- Export shortcuts reference
- Video tutorials

---

## 💶 Pricing Models

### License Options

| Tier | Features | Price |
|------|----------|-------|
| **Starter** | Single user, basic queries, CSV export | €X,XXX/year |
| **Professional** | Up to 10 users, reports, API access | €XX,XXX/year |
| **Enterprise** | Unlimited users, custom integrations, SLA | Custom |

### Implementation Services

- **Initial Setup:** €X,XXX (one-time)
- **Custom ETL:** €X,XXX (per data source)
- **Training:** €X,XXX (per session)
- **Support:** €X,XXX/year (optional)

---

## 📈 Success Metrics

Track ROI with built-in analytics:

- **Queries Executed:** Measure adoption
- **Time Saved:** Compare manual vs. automated analysis
- **Reports Generated:** Track knowledge sharing
- **Risk Detections:** Quantify compliance value

---

## 🚀 Getting Started

### Quick Start (15 minutes)

```bash
# 1. Clone repository
git clone https://github.com/your-org/paladino.git
cd paladino

# 2. Start Neo4j
docker-compose up -d

# 3. Install and configure
pip install -e .
cp .env.example .env

# 4. Load data
python scripts/run_anac_etl.py
python scripts/run_opencup_etl.py

# 5. Start investigating
paladino investigate
```

### Pilot Program

We recommend a **30-day pilot** to validate value:

**Week 1-2:** Setup and data loading
**Week 3:** User training and initial investigations
**Week 4:** ROI measurement and decision

---

## 📞 Contact & Next Steps

### Ready to Explore Paladino?

1. **Schedule a Demo** - See Paladino in action with your use cases
2. **Pilot Program** - 30-day trial with your data
3. **Custom Proposal** - Tailored to your organization's needs

### What We Need to Know

- Your primary use case (due diligence, journalism, compliance, etc.)
- Expected number of users
- Data sources you need integrated
- Deployment preference (on-prem/cloud)

---

## 📋 Appendix: Sample Queries

### Common Investigations

```
# Company Analysis
"Show me all tenders won by company XYZ"
"Which companies compete most with ABC?"
"Show corporate networks for company XYZ"

# Risk Detection
"Companies with high single-bidder ratios"
"Detect buyer concentration patterns"
"Show geographic anomalies in tenders"

# Cross-Source Analysis
"Link ANAC tenders to OpenCUP projects"
"Show PNRR-funded projects in Sicily"
"Companies winning both tenders and projects"

# Market Analysis
"Top 50 companies by region and sector"
"Market concentration in healthcare sector"
"New entrants in public procurement"
```

---

## 🏆 Why Choose Paladino?

✅ **Purpose-Built** - Designed for Italian public data
✅ **AI-Powered** - Natural language queries, no training needed
✅ **Production-Ready** - 85+ automated tests, enterprise-grade
✅ **Open Source** - Transparent, auditable, extensible
✅ **Local-First** - Your data, your infrastructure, your control
✅ **Fast ROI** - Payback in weeks, not months

---

**🛡️ Paladino - Justice & Data**

*Transforming fragmented public data into actionable intelligence*

---

*Document Version: 1.0*
*Last Updated: February 2026*
*Contact: [Your Contact Information]*
