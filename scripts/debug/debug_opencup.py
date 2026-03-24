from pathlib import Path

from paladino.etl.opencup_download import OpencupDownloader
from paladino.etl.opencup_transform import OpencupTransformer

file = Path("data/opencup/raw/OpenCup_Progetti1.csv")
downloader = OpencupDownloader()
transformer = OpencupTransformer()

print(f"Loading {file}...")
df = downloader.load_csv_to_dataframe(file)

print(f"Columns found: {df.columns}")
print(f"First row: {df.row(0)}")

# Try transformation
data = transformer.transform(df)
projects = data.get("projects")

print(f"Extracted projects count: {len(projects)}")
if not projects.is_empty():
    print(f"Project columns: {projects.columns}")
    print(f"First project: {projects.row(0)}")
else:
    print("NO PROJECTS EXTRACTED")
