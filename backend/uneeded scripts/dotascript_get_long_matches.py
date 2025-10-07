import psutil
import json
from datetime import datetime
import dotascript_helper_methods as dota_helper


startTime = datetime.now()
tournament_list = []
count = 0

with open("tournament_list.txt", "r") as f:
    for line in f:
        tournament_list.append(line)


with open("data/2025.jsonl", "r") as f:
    for line in f:
        try:
            match = json.loads(line)
            if((match["league_name"]+"\n") in tournament_list and match["duration"] > (60 * 60)):
                print(dota_helper.matchToString(match))
            count = count + 1
        except json.JSONDecodeError:
            print("ERROR!")
            continue


endTime = datetime.now()

print(f"\n\tParsed through {count:,} games in {endTime-startTime}\n")
