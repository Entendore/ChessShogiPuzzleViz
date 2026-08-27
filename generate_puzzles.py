import pandas as pd
import os

# Ensure the data directory exists (matches the path expected by app.py)
os.makedirs("data", exist_ok=True)

# Example Shogi puzzles (Tsume Shogi)
# SFEN format: board/turn/hand/move_number
# - Board: 9 rows separated by '/'. 1-9 for empty squares, lowercase for White (Gote), uppercase for Black (Sente).
# - Turn: 'b' for Black (Sente), 'w' for White (Gote)
# - Hand: Pieces in hand (e.g., 'R2G' = 1 Rook, 2 Golds). Use '-' for empty hand.
# - Move number: Usually 1 for puzzles.

puzzles = [
    {
        "PuzzleId": "tsume_001",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b R2G 1",
        "Moves": "R*5b K4a G*4a",
        "Rating": 500,
        "RatingDeviation": 50,
        "Popularity": 95,
        "NbPlays": 1500,
        "Themes": "mateIn2",
        "GameUrl": "https://example.com/game/001",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_002",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b R2G 1",
        "Moves": "R*5b K6a G*6a",
        "Rating": 550,
        "RatingDeviation": 45,
        "Popularity": 92,
        "NbPlays": 1450,
        "Themes": "mateIn2",
        "GameUrl": "https://example.com/game/002",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_003",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b R2G2S 1",
        "Moves": "R*5b K4a S*4b K3a R*3b",
        "Rating": 800,
        "RatingDeviation": 60,
        "Popularity": 88,
        "NbPlays": 1200,
        "Themes": "mateIn3",
        "GameUrl": "https://example.com/game/003",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_004",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b B2R 1",
        "Moves": "R*5b K4a B*4b",
        "Rating": 900,
        "RatingDeviation": 55,
        "Popularity": 85,
        "NbPlays": 1100,
        "Themes": "mateIn2",
        "GameUrl": "https://example.com/game/004",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_005",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b R2G2S2N 1",
        "Moves": "R*5b K4a N*3b K3a R*3b",
        "Rating": 1100,
        "RatingDeviation": 70,
        "Popularity": 80,
        "NbPlays": 950,
        "Themes": "mateIn3,knightDrop",
        "GameUrl": "https://example.com/game/005",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_006",
        "SFEN": "4k4/9/9/9/9/9/9/4g4/9 b R2S 1",
        "Moves": "R*5b K4a S*4b K3a S*3b",
        "Rating": 1200,
        "RatingDeviation": 65,
        "Popularity": 75,
        "NbPlays": 800,
        "Themes": "mateIn3",
        "GameUrl": "https://example.com/game/006",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_007",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b R2L 1",
        "Moves": "R*5b K6a L*6b",
        "Rating": 600,
        "RatingDeviation": 50,
        "Popularity": 90,
        "NbPlays": 1300,
        "Themes": "mateIn2,lanceDrop",
        "GameUrl": "https://example.com/game/007",
        "OpeningTags": "Hirate"
    },
    {
        "PuzzleId": "tsume_008",
        "SFEN": "4k4/9/9/9/9/9/9/9/9 b R2P 1",
        "Moves": "R*5b K4a P*4b",
        "Rating": 700,
        "RatingDeviation": 55,
        "Popularity": 89,
        "NbPlays": 1250,
        "Themes": "mateIn2,pawnDrop",
        "GameUrl": "https://example.com/game/008",
        "OpeningTags": "Hirate"
    }
]

# Create a DataFrame
df = pd.DataFrame(puzzles)

# Save to Parquet
output_path = "data/shogi_puzzles.parquet"
df.to_parquet(output_path, engine="pyarrow", index=False)

print(f"✅ Successfully generated {len(puzzles)} example Shogi puzzles.")
print(f"📁 Saved to: {os.path.abspath(output_path)}")
print("\nYou can now run `python app.py` and the app will automatically detect and load this file!")