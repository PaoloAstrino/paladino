
import polars as pl
from paladino.etl.opencup_transform import OpencupTransformer
from paladino.etl.opencup_download import OpencupDownloader
from pathlib import Path

downloader = OpencupDownloader()
transformer = OpencupTransformer()

loc_file = Path("data/opencup/raw/OpenCup_Localizzazione.csv")
if loc_file.exists():
    df = downloader.load_csv_to_dataframe(loc_file)
    print(f"Localization columns: {df.columns}")
    print(f"Localization schema: {df.schema}")
    print(f"Localization preview: {df.head(2)}")
    loc_data = transformer.extract_localization(df.head(10))
    print(f"Extracted Loc Data Head: {loc_data.head(2)}")

sub_file = Path("data/opencup/raw/OpenCup_Soggetti.csv")
if sub_file.exists():
    df = downloader.load_csv_to_dataframe(sub_file)
    print(f"Subjects columns: {df.columns}")
    print(f"Subjects schema: {df.schema}")
    print(f"Subjects preview: {df.head(2)}")
    sub_data = transformer.extract_subjects(df.head(10))
    print(f"Extracted Sub Data Head: {sub_data.head(2)}")
