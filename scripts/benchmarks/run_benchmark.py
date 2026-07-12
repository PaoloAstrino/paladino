"""
Performance Benchmarking Suite for Paladino.
Measures ETL throughput, query latency, and memory usage.
"""

import time
import cProfile
import pstats
import io
import argparse
from loguru import logger
import psutil
import os
from paladino.db import Neo4jConnection

class PaladinoProfiler:
    def __init__(self):
        self.pr = cProfile.Profile()
        self.start_time = 0
        self.start_mem = 0

    def start(self):
        self.start_time = time.perf_counter()
        self.start_mem = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        self.pr.enable()

    def stop(self, task_name: str):
        self.pr.disable()
        end_time = time.perf_counter()
        end_mem = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        
        duration = end_time - self.start_time
        mem_delta = end_mem - self.start_mem
        
        logger.info(f"BENCHMARK [{task_name}]: Duration: {duration:.2f}s, Peak Mem Delta: {mem_delta:.2f}MB")
        
        # Save stats
        s = io.StringIO()
        ps = pstats.Stats(self.pr, stream=s).sort_stats('tottime')
        ps.print_stats(20)
        
        output_dir = "benchmarks/output"
        os.makedirs(output_dir, exist_ok=True)
        with open(f"{output_dir}/{task_name}_profile.txt", "w") as f:
            f.write(s.getvalue())

def run_query_stress(conn: Neo4jConnection, count: int):
    """Run a suite of common queries and measure P95 latency."""
    latencies = []
    queries = [
        "MATCH (c:Company) RETURN count(c)",
        "MATCH (c:Company) WHERE c.risk_score > 0.5 RETURN c.nome_normalizzato LIMIT 10",
        "MATCH (c:Company)-[:WINS]->(t:Tender) RETURN c.nome_normalizzato, count(t) as wins ORDER BY wins DESC LIMIT 10"
    ]
    
    for i in range(count):
        q = queries[i % len(queries)]
        start = time.perf_counter()
        conn.run_query(q)
        latencies.append(time.perf_counter() - start)
        
    latencies.sort()
    avg = sum(latencies) / len(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    logger.success(f"Query Stress Test ({count} queries): Avg: {avg*1000:.2f}ms, P95: {p95*1000:.2f}ms")

def run_etl_benchmark():
    """Run the PNRR ETL pipeline as a subprocess and measure performance."""
    import subprocess
    import sys
    from pathlib import Path
    
    script_path = Path(__file__).parent.parent / "etl" / "run_pnnr_etl.py"
    subprocess.run([sys.executable, str(script_path)], check=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["etl", "confidence", "queries"], required=True)
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()
    
    profiler = PaladinoProfiler()
    profiler.start()
    
    conn = Neo4jConnection()
    try:
        if args.task == "queries":
            run_query_stress(conn, args.count)
        elif args.task == "etl":
            run_etl_benchmark()
        # Confidence task hook will be added next
    finally:
        conn.close()
        profiler.stop(args.task)
