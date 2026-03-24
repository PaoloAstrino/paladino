"""
End-to-end test for GraphRAG agent with LLM integration.
"""

import pytest

from paladino.app.graphrag_agent import GraphRAGAgent


@pytest.mark.slow
def test_graphrag_full_workflow(clean_neo4j, mock_ollama):
    """
    E2E test for complete GraphRAG workflow.

    This test:
    1. Creates a complete graph (companies, tenders, projects, geography)
    2. Uses LLM to classify natural language query
    3. Executes appropriate Cypher template
    4. Returns structured results
    """
    # 1. Create complete test graph
    with clean_neo4j.session() as session:
        session.run("""
            // Create geographic hierarchy
            CREATE (r:Region {cod_regione: '03', nome: 'Lombardia', source: 'TEST'})
            CREATE (p:Province {cod_provincia: '015', sigla: 'MI', nome: 'Milano', source: 'TEST'})
            CREATE (m:Municipality {cod_istat: '058091', nome: 'Milano', popolazione: 1352000, source: 'TEST'})
            CREATE (m)-[:IN_PROVINCE]->(p)
            CREATE (m)-[:IN_REGION]->(r)
            CREATE (p)-[:IN_REGION]->(r)
            
            // Create companies
            CREATE (c1:Company {
                cf: 'COMPANY1',
                nome_normalizzato: 'ACME COSTRUZIONI',
                risk_score: 0.3,
                total_tenders: 15,
                source: 'TEST'
            })
            CREATE (c2:Company {
                cf: 'COMPANY2',
                nome_normalizzato: 'BETA ENGINEERING',
                risk_score: 0.85,
                anomaly_flags: ['high_single_bidder_rate', 'buyer_concentration'],
                total_tenders: 8,
                source: 'TEST'
            })
            
            // Link companies to municipality
            CREATE (c1)-[:LOCATED_IN]->(m)
            CREATE (c2)-[:LOCATED_IN]->(m)
            
            // Create tenders
            CREATE (t1:Tender {cig: 'T1', importo: 150000.0, oggetto: 'IT services', source: 'TEST'})
            CREATE (t2:Tender {cig: 'T2', importo: 200000.0, oggetto: 'Construction', source: 'TEST'})
            
            // Create WINS relationships
            CREATE (c1)-[:WINS {importo: 145000.0}]->(t1)
            CREATE (c2)-[:WINS {importo: 195000.0}]->(t2)
            
            // Create project
            CREATE (proj:Project {
                cup: 'J12345678901234',
                titolo: 'Digital transformation',
                importo_finanziato: 1000000.0,
                regione: 'Lombardia',
                source: 'TEST'
            })
            
            // Create funding source
            CREATE (f:FundingSource {nome: 'PNRR', tipo: 'EU', source: 'TEST'})
            
            // Create relationships
            CREATE (t1)-[:PART_OF_PROJECT {confidence: 0.95}]->(proj)
            CREATE (proj)-[:FUNDED_BY]->(f)
        """)

    # 2. Initialize agent
    agent = GraphRAGAgent(clean_neo4j)

    # 3. Test different query types

    # Query 1: Companies by region
    mock_ollama.return_value.json.return_value = {
        "message": {
            "content": '{"template_name": "companies_by_region", "params": {"region": "Lombardia"}}'
        }
    }

    result1 = agent.natural_language_query("Which companies are in Lombardia?")

    assert result1["template"] == "companies_by_region"
    assert len(result1["results"]) == 2
    assert any(r["company"] == "ACME COSTRUZIONI" for r in result1["results"])

    # Query 2: High risk companies
    mock_ollama.return_value.json.return_value = {
        "message": {
            "content": '{"template_name": "high_risk_companies", "params": {"min_risk": 0.5}}'
        }
    }

    result2 = agent.natural_language_query("Show me high risk companies")

    assert result2["template"] == "high_risk_companies"
    assert len(result2["results"]) == 1
    assert result2["results"][0]["nome_normalizzato"] == "BETA ENGINEERING"
    assert result2["results"][0]["risk_score"] == 0.85

    # Query 3: PNRR projects
    mock_ollama.return_value.json.return_value = {
        "message": {"content": '{"template_name": "pnrr_projects", "params": {}}'}
    }

    result3 = agent.natural_language_query("What PNRR projects do we have?")

    assert result3["template"] == "pnrr_projects"
    assert len(result3["results"]) == 1
    assert result3["results"][0]["cup"] == "J12345678901234"

    # Query 4: Regional spending
    mock_ollama.return_value.json.return_value = {
        "message": {"content": '{"template_name": "regional_spending", "params": {}}'}
    }

    result4 = agent.natural_language_query("Show me spending by region")

    assert result4["template"] == "regional_spending"
    assert len(result4["results"]) >= 1
    assert any(r["regione"] == "Lombardia" for r in result4["results"])


@pytest.mark.slow
def test_graphrag_multi_hop_reasoning(clean_neo4j):
    """
    E2E test for multi-hop graph traversal.

    Tests complex queries that require multiple relationship hops.
    """
    # Create test data
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {cf: 'CF1', nome_normalizzato: 'TEST CO', source: 'TEST'})
            CREATE (t:Tender {cig: 'CIG1', importo: 100000.0, source: 'TEST'})
            CREATE (proj:Project {cup: 'CUP1', titolo: 'Test Project', source: 'TEST'})
            CREATE (f:FundingSource {nome: 'PNRR', tipo: 'EU', source: 'TEST'})
            CREATE (m:Municipality {nome: 'Roma', source: 'TEST'})
            CREATE (r:Region {nome: 'Lazio', source: 'TEST'})
            
            CREATE (c)-[:WINS]->(t)
            CREATE (t)-[:PART_OF_PROJECT]->(proj)
            CREATE (proj)-[:FUNDED_BY]->(f)
            CREATE (c)-[:LOCATED_IN]->(m)
            CREATE (m)-[:IN_REGION]->(r)
        """)

    # Execute multi-hop query
    agent = GraphRAGAgent(clean_neo4j)

    # Custom query: Companies with PNRR projects
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (c:Company)-[:WINS]->(t:Tender)-[:PART_OF_PROJECT]->(p:Project)
                  -[:FUNDED_BY]->(f:FundingSource {nome: 'PNRR'})
            RETURN c.nome_normalizzato as company, p.titolo as project, count(t) as tenders
        """)

        records = [dict(r) for r in result]

        assert len(records) == 1
        assert records[0]["company"] == "TEST CO"
        assert records[0]["project"] == "Test Project"
        assert records[0]["tenders"] == 1
