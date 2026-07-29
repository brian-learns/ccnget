# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "duckdb",
#     "hf-transfer",
#     "huggingface-hub",
# ]
# ///

import duckdb
import random
from huggingface_hub import HfFileSystem

def main() -> None:

    # 1. Initialize your working filesystem and nested glob
    fs = HfFileSystem()
    repo_id = "brian-learns/cdx-cc-news"
    parquet_files = fs.glob(f"datasets/{repo_id}/data/**/**/*.parquet")

    print(f"Found {len(parquet_files)} partitioned parquet files to analyze.")
    parquet_files = [f"hf://{path}" for path in parquet_files]

    # 2. Optimize Network Performance
    # Shuffle files to mix up months, then select a subset.
    # This prevents DuckDB from having to read metadata from all 119 files over HTTP.
    random.shuffle(parquet_files)
    subset_files = parquet_files[:15] 
    print(f"Shuffled and selected 15 random files to minimize network handshake overhead.")

    # 3. Connect DuckDB and register your working HfFileSystem instance
    conn = duckdb.connect()
    duckdb.register_filesystem(fs)

    # 4. Generate the 100-row sample CSV
    output_100 = "sample_100.csv"
    print(f"\nStreaming data and exporting exactly 100 rows to {output_100}...")
    query_100 = f"""
        COPY (
            SELECT *
            FROM read_parquet(?)
            USING SAMPLE 100 ROWS (reservoir)
        ) TO '{output_100}' (FORMAT 'CSV', HEADER true);
    """
    conn.execute(query_100, [subset_files])
    print(f"Success: {output_100} created.")

    # 5. Generate the 1000-row sample CSV
    output_1000 = "sample_1000.csv"
    print(f"\nStreaming data and exporting exactly 1000 rows to {output_1000}...")
    query_1000 = f"""
        COPY (
            SELECT *
            FROM read_parquet(?)
            USING SAMPLE 1000 ROWS (reservoir)
        ) TO '{output_1000}' (FORMAT 'CSV', HEADER true);
    """
    conn.execute(query_1000, [subset_files])
    print(f"Success: {output_1000} created.")

    print("\n--- All CSV Exports Complete ---")


if __name__ == "__main__":
    main()

