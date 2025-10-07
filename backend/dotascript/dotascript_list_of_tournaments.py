import json
from datetime import datetime
import dotascript_helper_methods as dota_helper

league_names = []

with open("data/2025.jsonl", "r") as f:
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
