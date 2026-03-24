"""
The Oracle - Proactive Network Intelligence.
Generates an automatic investigative summary of the knowledge graph.
"""

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from paladino.db import Neo4jConnection
from paladino.constants import TEMPORAL_SPIKE_THRESHOLD

class Oracle:
    """
    Scans the graph for topological anomalies and high-risk patterns.
    Designed to be run after an ETL cycle.
    """
    
    def __init__(self, conn: Neo4jConnection):
        self.conn = conn
        self.console = Console()

    def get_cartel_alerts(self):
        """Top communities by spending density."""
        query = """
        MATCH (c:Company)-[:WINS]->(t:Tender)
        WHERE c.community_id IS NOT NULL
        RETURN c.community_id as community,
               count(DISTINCT c) as companies,
               count(t) as tender_count,
               sum(t.importo) as total_value
        ORDER BY total_value DESC
        LIMIT 3
        """
        return self.conn.run_query(query)

    def get_influencer_alerts(self):
        """Top companies by PageRank (Network Centrality)."""
        query = """
        MATCH (c:Company)
        WHERE c.centrality_score IS NOT NULL
        RETURN c.nome_originale as name,
               c.centrality_score as score,
               c.risk_score as risk
        ORDER BY score DESC
        LIMIT 3
        """
        return self.conn.run_query(query)

    def get_monopoly_alerts(self):
        """Top companies winning mostly single-bidder tenders."""
        query = """
        MATCH (c:Company)-[:WINS]->(t:Tender)
        WITH c, count(t) as total,
             sum(case when t.single_bidder = true then 1 else 0 end) as single_wins
        WHERE total > 5
        RETURN c.nome_originale as name,
               (toFloat(single_wins)/total) as ratio,
               total as total_wins
        ORDER BY ratio DESC
        LIMIT 3
        """
        return self.conn.run_query(query)

    # ------------------------------------------------------------------
    # Fraud Pattern scanners
    # ------------------------------------------------------------------

    def get_fraud_pattern_alerts(self, limit: int = 10):
        """
        Return the most recently detected FraudPattern nodes ordered by
        severity (critical first) then detection time.

        Parameters
        ----------
        limit : int
            Maximum number of patterns to return.
        """
        severity_order = "CASE f.severity " \
                         "WHEN 'critical' THEN 1 " \
                         "WHEN 'high'     THEN 2 " \
                         "WHEN 'medium'   THEN 3 " \
                         "ELSE                  4 END"
        return self.conn.run_query(
            f"""
            MATCH (f:FraudPattern)
            RETURN f.id              AS pattern_id,
                   f.pattern_name   AS pattern_name,
                   f.severity       AS severity,
                   f.description    AS description,
                   f.detected_at    AS detected_at,
                   size(f.affected_entity_ids) AS affected_count
            ORDER BY {severity_order} ASC, f.detected_at DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )

    def get_entities_by_pattern(self, pattern_name: str, limit: int = 20):
        """
        Return all entities (Company / Tender / Buyer) flagged by a specific
        named fraud pattern.

        Parameters
        ----------
        pattern_name : str
            Canonical pattern key, e.g. "bid_rotation", "split_tendering".
        limit : int
            Maximum results.
        """
        return self.conn.run_query(
            """
            MATCH (e)-[r:FLAGGED_BY]->(f:FraudPattern {pattern_name: $pattern_name})
            RETURN labels(e)[0]           AS entity_type,
                   coalesce(e.nome_normalizzato, e.nome, e.oggetto) AS entity_name,
                   e.id                  AS entity_id,
                   r.score               AS score,
                   r.detected_at         AS detected_at,
                   f.description         AS pattern_description
            ORDER BY r.score DESC
            LIMIT $limit
            """,
            {"pattern_name": pattern_name, "limit": limit},
        )

    def get_fraud_pattern_summary(self):
        """
        Aggregate count of FraudPattern nodes grouped by pattern name and
        severity for a quick dashboard overview.
        """
        return self.conn.run_query(
            """
            MATCH (f:FraudPattern)
            RETURN f.pattern_name AS pattern,
                   f.severity     AS severity,
                   count(f)       AS occurrences,
                   max(f.detected_at) AS last_seen
            ORDER BY occurrences DESC
            """
        )

    # ------------------------------------------------------------------
    # Supply-chain & corporate-network scanners
    # ------------------------------------------------------------------

    def get_supply_chain_alerts(self, limit: int = 5):
        """
        Top winners by outgoing SUBCONTRACTS_TO edges — possible pass-through
        entities routing money down the chain.

        Returns [] with a silent skip if no supply-chain data is loaded yet.
        """
        return self.conn.run_query(
            """
            MATCH (winner:Company)-[r:SUBCONTRACTS_TO]->(sub:Company)
            WITH winner,
                 count(DISTINCT sub.id)  AS distinct_subs,
                 count(r)                AS total_contracts,
                 collect(DISTINCT r.cig) AS cigs
            WHERE total_contracts >= 2
            RETURN winner.nome_normalizzato AS winner_name,
                   winner.id               AS winner_id,
                   distinct_subs,
                   total_contracts,
                   cigs[..5]              AS sample_cigs
            ORDER BY total_contracts DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )

    def get_corporate_network_summary(self):
        """
        Quick stats on corporate-graph coverage:
        - persons loaded
        - REPRESENTS edges (directors)
        - SHAREHOLDER_OF edges
        - SHARES_UBO edges
        - companies with ownership_influence score

        Returns a single-row dict (all values 0 when graph is unpopulated).
        """
        result = self.conn.run_query(
            """
            MATCH (p:Person)       WITH count(p) AS persons
            OPTIONAL MATCH ()-[r:REPRESENTS]->()   WITH persons, count(r) AS directors
            OPTIONAL MATCH ()-[s:SHAREHOLDER_OF]->() WITH persons, directors, count(s) AS shareholders
            OPTIONAL MATCH ()-[u:SHARES_UBO]->()  WITH persons, directors, shareholders, count(u) AS ubo_edges
            OPTIONAL MATCH (c:Company) WHERE c.ownership_influence IS NOT NULL
            RETURN persons, directors, shareholders, ubo_edges,
                   count(c) AS companies_with_influence
            """
        )
        return result[0] if result else {
            "persons": 0, "directors": 0, "shareholders": 0,
            "ubo_edges": 0, "companies_with_influence": 0,
        }

    def get_board_overlap_companies(self, limit: int = 5):
        """
        Top company pairs sharing the most board members.
        Returns [] with a silent skip if no REPRESENTS edges exist.
        """
        return self.conn.run_query(
            """
            MATCH (p:Person)-[:REPRESENTS]->(c1:Company)
            MATCH (p)-[:REPRESENTS]->(c2:Company)
            WHERE id(c1) < id(c2)
            WITH c1, c2, count(DISTINCT p) AS shared_count
            WHERE shared_count >= 1
            RETURN c1.nome_normalizzato AS company1,
                   c2.nome_normalizzato AS company2,
                   shared_count
            ORDER BY shared_count DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )

    def get_spike_alerts(self, threshold: float = TEMPORAL_SPIKE_THRESHOLD, limit: int = 5):
        """
        Return companies whose most recent quarter's activity exceeds
        ``threshold`` × their rolling mean — delegates to TemporalAnalyzer.

        Returns [] (silently) when date data has not yet been migrated.
        """
        try:
            from paladino.analytics.temporal_analytics import TemporalAnalyzer
            ta = TemporalAnalyzer(self.conn)
            return ta.detect_sudden_spikes(threshold=threshold, limit=limit)
        except Exception as exc:  # pragma: no cover
            logger.debug(f"[oracle] spike alerts skipped: {exc}")
            return []

    def run_investigative_summary(self):
        """Execute all scanners and print a beautiful report."""
        self.console.print("[bold magenta]🔮 THE PALADINO ORACLE - PROACTIVE SUMMARY[/bold magenta]")
        self.console.print("[dim]Scanning topological layers for structural risk...[/dim]")

        # 1. Influencers
        infl = self.get_influencer_alerts()
        if infl:
            table = Table(title="💎 High-Influence Hubs (PageRank)", box=box.ROUNDED)
            table.add_column("Company", style="cyan")
            table.add_column("Influence", justify="right", style="green")
            table.add_column("Risk Score", justify="right", style="yellow")
            for r in infl:
                table.add_row(r['name'], f"{r['score']:.4f}", f"{r['risk']:.2f}")
            self.console.print(table)

        # 2. Communities (Cartel Check)
        cartels = self.get_cartel_alerts()
        if cartels:
            table = Table(title="🏗️ High-Value Clusters (Community Detection)", box=box.ROUNDED)
            table.add_column("ID", style="dim")
            table.add_column("Nodes", justify="right")
            table.add_column("Tenders", justify="right")
            table.add_column("Total Value (€)", justify="right", style="bold green")
            for r in cartels:
                table.add_row(str(r['community']), str(r['companies']), str(r['tender_count']), f"{r['total_value']:,.2f}")
            self.console.print(table)

        # 3. Monopolies
        monop = self.get_monopoly_alerts()
        if monop:
            table = Table(title="🚩 Single-Bidder Specialists", box=box.ROUNDED)
            table.add_column("Company", style="cyan")
            table.add_column("Ratio", justify="right", style="red")
            table.add_column("Wins", justify="right")
            for r in monop:
                table.add_row(r['name'], f"{r['ratio']*100:.1f}%", str(r['total_wins']))
            self.console.print(table)

        # 4. Fraud Pattern Alerts
        fraud_alerts = self.get_fraud_pattern_alerts(limit=10)
        if fraud_alerts:
            table = Table(title="🔴 Fraud Pattern Detections", box=box.ROUNDED)
            table.add_column("Pattern", style="bold red")
            table.add_column("Severity", style="red")
            table.add_column("Entities", justify="right")
            table.add_column("Detected", style="dim")
            table.add_column("Description")
            for r in fraud_alerts:
                table.add_row(
                    r["pattern_name"],
                    r["severity"].upper(),
                    str(r["affected_count"]),
                    str(r["detected_at"])[:19],
                    r["description"][:80] + ("…" if len(r["description"]) > 80 else ""),
                )
            self.console.print(table)

        # 5. Fraud summary by pattern
        fraud_summary = self.get_fraud_pattern_summary()
        if fraud_summary:
            table = Table(title="📊 Fraud Pattern Summary", box=box.SIMPLE)
            table.add_column("Pattern", style="yellow")
            table.add_column("Severity")
            table.add_column("Count", justify="right", style="bold")
            table.add_column("Last Seen", style="dim")
            for r in fraud_summary:
                color = {"critical": "red", "high": "yellow",
                         "medium": "cyan", "low": "green"}.get(r["severity"], "white")
                table.add_row(
                    r["pattern"],
                    f"[{color}]{r['severity'].upper()}[/{color}]",
                    str(r["occurrences"]),
                    str(r["last_seen"])[:19],
                )
            self.console.print(table)

        # 6. Corporate network coverage
        corp = self.get_corporate_network_summary()
        if corp and corp.get("persons", 0) > 0:
            table = Table(title="🏢 Corporate Network Coverage", box=box.SIMPLE)
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right", style="bold")
            table.add_row("Persons (directors/owners)", str(corp["persons"]))
            table.add_row("Director links (REPRESENTS)", str(corp["directors"]))
            table.add_row("Shareholding edges", str(corp["shareholders"]))
            table.add_row("UBO derivation edges (SHARES_UBO)", str(corp["ubo_edges"]))
            table.add_row("Companies with influence score", str(corp["companies_with_influence"]))
            self.console.print(table)
        else:
            self.console.print(
                Panel(
                    "[yellow]Corporate network not yet loaded[/yellow]\n\n"
                    "Director and ownership data unlocks:\n"
                    "  • Board Overlap Collusion detection\n"
                    "  • UBO Conflict detection\n"
                    "  • Ownership-graph PageRank\n\n"
                    "Load data by dropping CSV files into [bold]data/corporate/raw/[/bold] then:\n"
                    "[bold white]  python scripts/run_supply_chain_etl.py --step corporate[/bold white]",
                    title="[blue]ℹ  Corporate Data[/blue]",
                    border_style="blue",
                )
            )

        # 7. Supply-chain pass-through risk
        sc_alerts = self.get_supply_chain_alerts(limit=5)
        if sc_alerts:
            table = Table(title="🔗 Top Supply-Chain Prime Contractors", box=box.ROUNDED)
            table.add_column("Winner", style="cyan")
            table.add_column("Distinct Subs", justify="right")
            table.add_column("Contract Links", justify="right", style="yellow")
            table.add_column("Sample CIGs", style="dim")
            for r in sc_alerts:
                table.add_row(
                    r["winner_name"] or r["winner_id"],
                    str(r["distinct_subs"]),
                    str(r["total_contracts"]),
                    ", ".join(r["sample_cigs"]),
                )
            self.console.print(table)
        else:
            self.console.print(
                Panel(
                    "[yellow]No SUBCONTRACTS_TO data loaded[/yellow]\n\n"
                    "Sub-contractor data is sourced from [bold]PNRR_Subappaltatori_Gare.csv[/bold].\n"
                    "Run the PNRR ETL to populate supply-chain links:\n"
                    "[bold white]  python scripts/run_supply_chain_etl.py --step subcontractors[/bold white]",
                    title="[blue]ℹ  Supply Chain[/blue]",
                    border_style="blue",
                )
            )

        # 8. Board overlap
        overlaps = self.get_board_overlap_companies(limit=5)
        if overlaps:
            table = Table(title="👥 Board Overlap (Shared Directors)", box=box.ROUNDED)
            table.add_column("Company A", style="cyan")
            table.add_column("Company B", style="cyan")
            table.add_column("Shared Members", justify="right", style="red")
            for r in overlaps:
                table.add_row(r["company1"], r["company2"], str(r["shared_count"]))
            self.console.print(table)

        # 9. Recent Activity Spikes
        spikes = self.get_spike_alerts(limit=5)
        if spikes:
            table = Table(title="📈 Recent Activity Spikes (vs Rolling Mean)", box=box.ROUNDED)
            table.add_column("Company", style="cyan")
            table.add_column("Peak Quarter", justify="center")
            table.add_column("Latest", justify="right")
            table.add_column("Prior Mean", justify="right")
            table.add_column("Spike ×", justify="right", style="bold red")
            for r in spikes:
                table.add_row(
                    r.get("company_name") or r.get("company_id", "?"),
                    f"{r.get('latest_year','?')} Q{r.get('latest_quarter','?')}",
                    str(int(r.get("latest_value", 0))),
                    str(round(r.get("prior_mean", 0), 1)),
                    f"{r.get('spike_ratio', 0):.2f}×",
                )
            self.console.print(table)
        else:
            self.console.print(
                Panel(
                    "[yellow]No spike data available yet.[/yellow]\n\n"
                    "Run the date migration then re-analyse:\n"
                    "[bold white]  python scripts/migrate_date_types.py[/bold white]\n"
                    "[bold white]  python scripts/run_temporal_analysis.py[/bold white]",
                    title="[blue]ℹ  Temporal Spikes[/blue]",
                    border_style="blue",
                )
            )

        self.console.print()
        self.console.print("[bold green]Scan Complete.[/bold green] "
                           "Use the REPL to investigate specific communities, companies, "
                           "or fraud patterns.")
        self.console.print()

if __name__ == "__main__":
    from paladino.db import Neo4jConnection
    conn = Neo4jConnection()
    oracle = Oracle(conn)
    oracle.run_investigative_summary()
    conn.close()
