
from paladino.db import get_driver
from paladino.etl.anac_loader import AnacNeo4jLoader
import polars as pl
from datetime import datetime

driver = get_driver()
loader = AnacNeo4jLoader(driver)

# Mock a company row
df = pl.DataFrame([{
    "id": "test-uuid",
    "cf": "01234567890",
    "piva": "IT01234567890",
    "nome_normalizzato": "TEST COMPANY SRL",
    "nome_originale": "Test Company S.r.l.",
    "source": ["ANAC"],
    "dataset_version": "2026-02",
    "retrieval_date": datetime.now().isoformat(),
    "confidence": 0.95
}])

try:
    loader.load_companies(df)
    print("Test company loaded successfully")
except Exception as e:
    print(f"FAILED: {e}")
finally:
    driver.close()
