import psutil
import json
from datetime import datetime
import dotascript_helper_methods as dota_helper


process = psutil.Process()
startTime = datetime.now()

# setup tournament_list
tournament_list = []
with open("backend/tournament_list.txt", "r") as f:
    for line in f:
        tournament_list.append(line)

# setup series
series = {}  # dictionary
with open("backend/data/2026.jsonl", "r") as f:
    for line in f:
        try:
            match = json.loads(line)
            if (match["league_name"] + "\n") in tournament_list:  # ensure the match is from a valid tournament
                series_id = match["series_id"]
                if series_id not in series:  # if this is the first series, create array
                    series[series_id] = []
                series[series_id].append(match)  # and then append to the array

        except json.JSONDecodeError:
            continue


for series_id in series:

    # ignore matches where series_id is invalid or not set
    if series_id == 0:
        continue

    # check to see if the series contains a long match
    containsLongMatch = False
    for match in series[series_id]:  # series[series_id] is an array
        if match["duration"] > 3600:
            containsLongMatch = True

    # output the match
    if containsLongMatch:
        print(f"{dota_helper.seriesToString(series[series_id])}")
        print(f"{dota_helper.epochToReadable(series[series_id][0]['start_time']):>50s} ||", end="")

        for match in series[series_id]:
            print(f"{dota_helper.formatSeconds(match['duration']):<11s} ", end="")

        print(f"\n{'':>50s} || ", end="")
        for match in series[series_id]:
            print(f"{match['match_id']:<11d} ", end="")

        print("\n")


print(f"{(process.memory_info().rss / 1000000):.1f} MB")  # in MB
timeDelta = datetime.now() - startTime
print(f"{timeDelta} seconds")
