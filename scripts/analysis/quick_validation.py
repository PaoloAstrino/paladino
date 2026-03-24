#!/usr/bin/env python3
"""
Quick validation script to verify Paladino is working.
Run this after setup to confirm everything functions.

Usage:
    python scripts/quick_validation.py
"""

import sys


def check_neo4j():
    """Verify Neo4j connection."""
    from paladino.db import get_driver

    try:
        driver = get_driver()
        with driver.session() as session:
            result = session.run("RETURN 1 as test").single()
            if result["test"] == 1:
                print("   ✅ Neo4j connection successful")
                return True
    except Exception as e:
        print(f"   ❌ Neo4j connection failed: {e}")
        print("   💡 Solution: Run 'docker-compose up -d' to start Neo4j")
        return False


def check_data_loaded():
    """Verify data is loaded."""
    from paladino.db import get_driver

    driver = get_driver()
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN count(n) as count").single()
        count = result["count"]
        if count > 0:
            print(f"   ✅ Data loaded: {count} nodes in graph")

            # Show breakdown by label
            result = session.run("""
                MATCH (n) 
                RETURN labels(n)[0] as label, count(n) as count 
                ORDER BY count DESC 
                LIMIT 5
            """)
            print("   Top node types:")
            for record in result:
                print(f"      - {record['label']}: {record['count']}")
            return True
        else:
            print("   ⚠️  No data loaded. Run ETL pipelines first.")
            print("   💡 Solution: Run 'python scripts/run_anac_etl.py'")
            return False


def check_schema():
    """Verify schema is initialized."""
    from paladino.db import get_driver

    driver = get_driver()
    with driver.session() as session:
        constraints = session.run("SHOW CONSTRAINTS").list()
        indexes = session.run("SHOW INDEXES").list()

        if len(constraints) > 0 and len(indexes) > 0:
            print(
                f"   ✅ Schema initialized: {len(constraints)} constraints, {len(indexes)} indexes"
            )
            return True
        else:
            print("   ❌ Schema not initialized")
            print("   💡 Solution: Run 'python scripts/init_schema.py'")
            return False


def check_api():
    """Verify API starts."""
    import requests

    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ API responding: {data.get('status', 'healthy')}")
            return True
        else:
            print(f"   ❌ API returned {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("   ⚠️  API not running (optional - start with: paladino work)")
        return None  # Not a failure, just not running
    except Exception as e:
        print(f"   ❌ API check failed: {e}")
        return False


def check_templates():
    """Verify query templates work."""
    from paladino.app.graphrag_agent import CypherQueryTemplates

    try:
        templates = CypherQueryTemplates()
        template_list = templates.list_templates()
        if len(template_list) > 5:
            print(f"   ✅ {len(template_list)} query templates available")
            return True
        else:
            print(f"   ⚠️  Only {len(template_list)} templates found")
            return False
    except Exception as e:
        print(f"   ❌ Template check failed: {e}")
        return False


def check_cli():
    """Verify CLI is installed."""
    import subprocess

    try:
        result = subprocess.run(
            [sys.executable, "-m", "paladino.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and "Paladino" in result.stdout:
            print("   ✅ CLI installed and working")
            return True
        else:
            print("   ⚠️  CLI not responding")
            return False
    except Exception as e:
        print(f"   ❌ CLI check failed: {e}")
        return False


def main():
    print("\n" + "=" * 60)
    print("🔍 PALADINO QUICK VALIDATION")
    print("=" * 60 + "\n")

    checks = [
        ("Neo4j Connection", check_neo4j),
        ("Schema Initialized", check_schema),
        ("Data Loaded", check_data_loaded),
        ("API Running", check_api),
        ("Query Templates", check_templates),
        ("CLI Installed", check_cli),
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

    print("\n\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    for status, name, result in results:
        print(f"{status} {name}: {result}")

    passed = sum(1 for _, _, r in results if r == "PASS")
    skipped = sum(1 for _, _, r in results if r == "SKIPPED")
    total = len([r for r in results if r[2] != "SKIPPED"])

    print(
        f"\nResult: {passed}/{total} checks passed" + (f" ({skipped} skipped)" if skipped else "")
    )

    if passed == total:
        print("\n🎉 SUCCESS! Paladino is working correctly!")
        print("\n📝 Next steps:")
        print("   - Run: paladino investigate  (interactive mode)")
        print("   - Run: paladino stats  (view graph statistics)")
        print("   - Run: paladino work  (start API server)")
        print("   - Read: VALIDATION_PLAN.md  (comprehensive testing)")
        return 0
    else:
        print("\n⚠️  Some checks failed. Review the output above.")
        print("\n📝 Troubleshooting:")
        print("   1. Ensure Neo4j is running: docker-compose up -d")
        print("   2. Initialize schema: python scripts/init_schema.py")
        print("   3. Load sample data: python scripts/run_anac_etl.py --sample")
        print("   4. Check .env configuration")
        return 1


if __name__ == "__main__":
    sys.exit(main())
