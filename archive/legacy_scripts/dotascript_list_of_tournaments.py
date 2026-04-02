import json
from datetime import datetime

league_names = []

with open("backend/data/2026.jsonl", "r") as f:
    for line in f:
        try:
            match = json.loads(line)
            if match["league_name"] not in league_names:
                league_names.append(match["league_name"])


        except json.JSONDecodeError:
            print("ERROR!")
            continue

for name in league_names:
    print(name)
