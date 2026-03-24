#!/usr/bin/env python3
"""
Paladino Test Suite - Real Functionality Tests

Run this to test all working features of your Paladino installation.

Usage:
    python scripts/test_implementation.py
"""

import sys

from rich import box
from rich.console import Console
from rich.panel import Panel

from paladino.app.graphrag_agent import CypherQueryTemplates
from paladino.db import get_driver

console = Console()


def test_connection():
    """Test 1: Neo4j Connection"""
    console.print(Panel("TEST 1: Neo4j Connection", style="bold cyan"))
    try:
        driver = get_driver()
        with driver.session() as session:
            result = session.run("RETURN 1 as test").single()
            if result["test"] == 1:
                console.print("[green]✅ PASS[/green] - Neo4j connection working\n")
                return True
    except Exception as e:
        console.print(f"[red]❌ FAIL[/red] - {e}\n")
        return False


def test_data_loaded():
    """Test 2: Data is loaded"""
    console.print(Panel("TEST 2: Data Loaded", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN count(n) as total").single()
        count = result["total"]
        if count > 0:
            console.print(f"[green]✅ PASS[/green] - {count:,} nodes in graph\n")
            return True
        else:
            console.print("[red]❌ FAIL[/red] - No data loaded\n")
            return False


def test_node_types():
    """Test 3: Multiple node types exist"""
    console.print(Panel("TEST 3: Node Types", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH (n) 
            RETURN labels(n)[0] as label, count(n) as count 
            ORDER BY count DESC
        """)
        types = list(result)
        if len(types) >= 5:
            console.print(f"[green]✅ PASS[/green] - {len(types)} node types found:\n")
            for t in types[:8]:
                console.print(f"   - {t['label']}: {t['count']:,}")
            console.print()
            return True
        else:
            console.print("[red]❌ FAIL[/red] - Not enough node types\n")
            return False


def test_relationships():
    """Test 4: Relationships exist"""
    console.print(Panel("TEST 4: Relationships", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH ()-[r]->() 
            RETURN type(r) as type, count(r) as count 
            ORDER BY count DESC
        """)
        rels = list(result)
        if len(rels) >= 3:
            console.print(f"[green]✅ PASS[/green] - {len(rels)} relationship types:\n")
            for r in rels[:6]:
                console.print(f"   - {r['type']}: {r['count']:,}")
            console.print()
            return True
        else:
            console.print("[red]❌ FAIL[/red] - Not enough relationships\n")
            return False


def test_companies():
    """Test 5: Company data query"""
    console.print(Panel("TEST 5: Company Analysis", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        query = """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            RETURN c.nome_normalizzato as name, count(t) as tenders
            ORDER BY tenders DESC
            LIMIT 5
        """
        result = session.run(query)
        companies = list(result)
        if len(companies) > 0:
            console.print("[green]✅ PASS[/green] - Company analysis working:\n")
            for c in companies:
                console.print(f"   - {c['name']}: {c['tenders']} tenders")
            console.print()
            return True
        else:
            console.print("[yellow]⚠️  WARNING[/yellow] - No company data\n")
            return False


def test_cross_source():
    """Test 6: Cross-source links (ANAC to OpenCUP)"""
    console.print(Panel("TEST 6: Cross-Source Links", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        query = """
            MATCH (t:Tender)-[:PART_OF_PROJECT]->(p:Project)
            RETURN t.cig as cig, p.cup as cup
            LIMIT 5
        """
        result = session.run(query)
        links = list(result)
        if len(links) > 0:
            console.print(f"[green]✅ PASS[/green] - {len(links)} cross-source links found:\n")
            for link in links:
                console.print(f"   - CIG: {link['cig']} → CUP: {link['cup']}")
            console.print()
            return True
        else:
            console.print("[yellow]⚠️  WARNING[/yellow] - No cross-source links yet\n")
            return False


def test_geographic():
    """Test 7: Geographic data"""
    console.print(Panel("TEST 7: Geographic Distribution", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        query = """
            MATCH (c:Company)-[:LOCATED_IN]->(m:Municipality)-[:IN_REGION]->(r:Region)
            RETURN r.nome as region, count(c) as companies
            ORDER BY companies DESC
            LIMIT 5
        """
        result = session.run(query)
        regions = list(result)
        if len(regions) > 0:
            console.print("[green]✅ PASS[/green] - Geographic data working:\n")
            for r in regions:
                console.print(f"   - {r['region']}: {r['companies']:,} companies")
            console.print()
            return True
        else:
            console.print("[yellow]⚠️  WARNING[/yellow] - No geographic data\n")
            return False


def test_templates():
    """Test 8: Query templates"""
    console.print(Panel("TEST 8: Query Templates", style="bold cyan"))
    try:
        templates = CypherQueryTemplates()
        template_list = templates.list_templates()
        if len(template_list) >= 5:
            console.print(f"[green]✅ PASS[/green] - {len(template_list)} templates available:\n")
            for t in template_list[:8]:
                console.print(f"   - {t}")
            console.print()
            return True
        else:
            console.print("[red]❌ FAIL[/red] - Not enough templates\n")
            return False
    except Exception as e:
        console.print(f"[red]❌ FAIL[/red] - {e}\n")
        return False


def test_buyer_data():
    """Test 9: Buyer data"""
    console.print(Panel("TEST 9: Buyer Analysis", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        query = """
            MATCH (b:Buyer)-[:ISSUES]->(t:Tender)
            RETURN b.nome as buyer, count(t) as tenders
            ORDER BY tenders DESC
            LIMIT 5
        """
        result = session.run(query)
        buyers = list(result)
        if len(buyers) > 0:
            console.print("[green]✅ PASS[/green] - Buyer data working:\n")
            for b in buyers:
                console.print(f"   - {b['buyer']}: {b['tenders']} tenders")
            console.print()
            return True
        else:
            console.print("[yellow]⚠️  WARNING[/yellow] - No buyer data\n")
            return False


def test_versioning():
    """Test 10: Data versioning/provenance"""
    console.print(Panel("TEST 10: Data Versioning", style="bold cyan"))
    driver = get_driver()
    with driver.session() as session:
        result = session.run("MATCH (v:SchemaVersion) RETURN v.version as version").single()
        if result:
            console.print(f"[green]✅ PASS[/green] - Schema version: {result['version']}\n")
            return True
        else:
            console.print("[yellow]⚠️  WARNING[/yellow] - No version tracking\n")
            return False


def main():
    """Run all tests."""
    console.print("\n")
    console.print(
        Panel.fit(
            "PALADINO IMPLEMENTATION TEST SUITE\n" + "Testing all working features",
            style="bold magenta",
            box=box.DOUBLE,
        )
    )
    console.print()

    tests = [
        ("Neo4j Connection", test_connection),
        ("Data Loaded", test_data_loaded),
        ("Node Types", test_node_types),
        ("Relationships", test_relationships),
        ("Company Analysis", test_companies),
        ("Cross-Source Links", test_cross_source),
        ("Geographic Data", test_geographic),
        ("Query Templates", test_templates),
        ("Buyer Analysis", test_buyer_data),
        ("Data Versioning", test_versioning),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            console.print(f"[red]❌ ERROR[/red] in {name}: {e}\n")
            results.append(False)

    # Summary
    passed = sum(results)
    total = len(results)

    console.print("\n" + "=" * 60)
    console.print("TEST SUMMARY")
    console.print("=" * 60)
    console.print(f"\nPassed: {passed}/{total}")

    if passed == total:
        console.print("\n[green]🎉 ALL TESTS PASSED![/green]")
        console.print("\n[bold]Your Paladino implementation is fully functional![/bold]\n")
    elif passed >= total * 0.7:
        console.print("\n[yellow]✅ MOST TESTS PASSED[/yellow]")
        console.print("\n[bold]Core functionality is working![/bold]\n")
    else:
        console.print("\n[red]⚠️  SEVERAL TESTS FAILED[/red]")
        console.print("\nCheck the output above for details.\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
