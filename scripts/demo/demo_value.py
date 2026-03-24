#!/usr/bin/env python3
"""
Paladino Value Demonstration Script

This script demonstrates the tangible value Paladino delivers by answering
real business questions about Italian public spending data.

Run this after loading data to see Paladino in action.

Usage:
    python scripts/demo_value.py
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from paladino.db import get_driver

console = Console()


def print_header(text: str):
    """Print a section header."""
    console.print(Panel(text, style="bold magenta", box=box.DOUBLE))


def print_query(query: str):
    """Print a Cypher query."""
    console.print(f"\n[cyan]Query:[/cyan] {query}")


def print_results(results: list, title: str = "Results"):
    """Print results in a table."""
    if not results:
        console.print("[yellow]No results found[/yellow]")
        return
    
    table = Table(title=title, box=box.ROUNDED)
    
    # Add columns from first result
    if results:
        for key in results[0].keys():
            table.add_column(key, style="green")
    
    # Add rows (limit to 10 for display)
    for row in results[:10]:
        table.add_row(*[str(v) for v in row.values()])
    
    console.print(table)
    
    if len(results) > 10:
        console.print(f"[dim]... and {len(results) - 10} more results[/dim]")


def demo_basic_stats():
    """Show basic graph statistics."""
    print_header("📊 BASIC GRAPH STATISTICS")
    
    driver = get_driver()
    with driver.session() as session:
        # Total nodes
        result = session.run("MATCH (n) RETURN count(n) as total").single()
        console.print(f"\nTotal nodes in graph: [green]{result['total']}[/green]")
        
        # Node breakdown
        result = session.run("""
            MATCH (n) 
            RETURN labels(n)[0] as label, count(n) as count 
            ORDER BY count DESC
        """)
        results = [dict(r) for r in result]
        print_results(results, "Node Types")
        
        # Relationships
        result = session.run("""
            MATCH ()-[r]->() 
            RETURN type(r) as type, count(r) as count 
            ORDER BY count DESC
        """)
        results = [dict(r) for r in result]
        print_results(results, "Relationship Types")


def demo_top_companies():
    """Show top companies by tenders won."""
    print_header("🏆 TOP COMPANIES BY TENDERS WON")
    
    driver = get_driver()
    with driver.session() as session:
        query = """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            RETURN c.nome_normalizzato as Company, 
                   c.cf as CF,
                   count(t) as Tenders_Won,
                   sum(t.importo) as Total_Amount
            ORDER BY Tenders_Won DESC
            LIMIT 10
        """
        print_query(query)
        result = session.run(query)
        results = [dict(r) for r in result]
        print_results(results, "Top 10 Companies")


def demo_risk_analysis():
    """Demonstrate risk detection capabilities."""
    print_header("⚠️  RISK ANALYSIS DEMO")
    
    driver = get_driver()
    with driver.session() as session:
        # Companies with high single-bidder ratio
        query = """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WITH c, count(t) as total_wins,
                 sum(CASE WHEN t.single_bidder = true THEN 1 ELSE 0 END) as single_bidder_wins
            WHERE total_wins >= 3
            WITH c, single_bidder_wins, total_wins, 
                 (single_bidder_wins * 1.0 / total_wins) as ratio
            WHERE ratio > 0.5
            RETURN c.nome_normalizzato as Company,
                   total_wins as Total_Tenders,
                   single_bidder_wins as Single_Bidder,
                   round(ratio * 100, 1) as Single_Bidder_Ratio
            ORDER BY ratio DESC
            LIMIT 10
        """
        print_query(query)
        console.print("\n[yellow]Companies with >50% single-bidder tenders (potential risk indicator):[/yellow]")
        result = session.run(query)
        results = [dict(r) for r in result]
        print_results(results, "High Risk Companies")


def demo_cross_source():
    """Demonstrate cross-source analysis."""
    print_header("🔗 CROSS-SOURCE ANALYSIS")
    
    driver = get_driver()
    with driver.session() as session:
        # Tenders linked to projects
        query = """
            MATCH (t:Tender)-[:PART_OF_PROJECT]->(p:Project)
            RETURN t.cig as Tender_CIG,
                   p.cup as Project_CUP,
                   p.titolo as Project_Title,
                   t.importo as Tender_Amount
            LIMIT 10
        """
        print_query(query)
        console.print("\n[cyan]Tenders linked to OpenCUP projects:[/cyan]")
        result = session.run(query)
        results = [dict(r) for r in result]
        print_results(results, "Cross-Source Links")


def demo_geographic_analysis():
    """Show geographic distribution."""
    print_header("🗺️  GEOGRAPHIC ANALYSIS")
    
    driver = get_driver()
    with driver.session() as session:
        # Tenders by region
        query = """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE c.regione IS NOT NULL
            RETURN c.regione as Region,
                   count(t) as Tenders,
                   sum(t.importo) as Total_Amount
            ORDER BY Tenders DESC
            LIMIT 10
        """
        print_query(query)
        console.print("\n[cyan]Tenders by region:[/cyan]")
        result = session.run(query)
        results = [dict(r) for r in result]
        print_results(results, "Geographic Distribution")


def demo_buyer_analysis():
    """Analyze procurement buyers."""
    print_header("🏛️  BUYER ANALYSIS")
    
    driver = get_driver()
    with driver.session() as session:
        # Top buyers
        query = """
            MATCH (b:Buyer)-[:ISSUES]->(t:Tender)
            RETURN b.nome as Buyer,
                   count(t) as Tenders_Issued,
                   sum(t.importo) as Total_Spent
            ORDER BY Tenders_Issued DESC
            LIMIT 10
        """
        print_query(query)
        console.print("\n[cyan]Top procurement buyers:[/cyan]")
        result = session.run(query)
        results = [dict(r) for r in result]
        print_results(results, "Top Buyers")


def demo_value_summary():
    """Show value summary."""
    print_header("💡 VALUE DELIVERED BY PALADINO")
    
    console.print("""
[green]✅ What Paladino Enables:[/green]

1. [bold]Instant Multi-Source Analysis[/bold]
   - Before: Manual cross-referencing (hours/days)
   - After: Single query (seconds)

2. [bold]Risk Detection[/bold]
   - Automated anomaly detection
   - Single-bidder ratio analysis
   - Buyer concentration patterns

3. [bold]Cross-Source Intelligence[/bold]
   - Link ANAC tenders to OpenCUP projects
   - Trace money flow across sources
   - Impossible with manual analysis

4. [bold]Provenance Tracking[/bold]
   - Know where every data point came from
   - Audit trail for compliance
   - Confidence scores for decisions

5. [bold]Natural Language Queries[/bold]
   - No SQL/Cypher knowledge required
   - Ask questions in Italian
   - GraphRAG-powered understanding
""")
    
    console.print(Panel(
        "🎯 Paladino turns fragmented public data into actionable intelligence",
        style="bold green",
        box=box.DOUBLE
    ))


def main():
    """Run the value demonstration."""
    console.print("\n")
    console.print(Panel.fit(
        "🛡️  PALADINO VALUE DEMONSTRATION\n" +
        "Italian Public Funds Knowledge Graph",
        style="bold magenta",
        box=box.DOUBLE
    ))
    
    try:
        # Try to connect
        driver = get_driver()
        with driver.session() as session:
            session.run("RETURN 1")
    except Exception as e:
        console.print(f"\n[red]❌ Cannot connect to Neo4j: {e}[/red]")
        console.print("\n[yellow]💡 Solution:[/yellow]")
        console.print("   1. Start Neo4j: docker-compose up -d")
        console.print("   2. Load data: python scripts/run_anac_etl.py")
        console.print("   3. Run this demo again")
        return 1
    
    # Run demos
    demo_basic_stats()
    demo_top_companies()
    demo_risk_analysis()
    demo_cross_source()
    demo_geographic_analysis()
    demo_buyer_analysis()
    demo_value_summary()
    
    console.print("\n[green]✨ Demo complete![/green]")
    console.print("\n[cyan]Next steps:[/cyan]")
    console.print("   - Try: paladino investigate  (interactive mode)")
    console.print("   - Try: paladino work  (start API)")
    console.print("   - Read: VALIDATION_PLAN.md  (comprehensive testing)")
    console.print()
    
    return 0


if __name__ == "__main__":
    exit(main())
