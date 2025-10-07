import psutil
import json
from datetime import datetime
import dotascript_helper_methods as dota_helper


process = psutil.Process()
startTime = datetime.now()

tournament_list_path = f"/home/tankionlinefirstseargent/python/dotascript/tournament_list.txt"
data_path = f"/home/tankionlinefirstseargent/python/dotascript/data/2025.jsonl"
output_path = f"/home/tankionlinefirstseargent/python/dotascript/output.txt"


# setup tournament_list
tournament_list = []
with open(tournament_list_path, "r") as f:
    for line in f:
        tournament_list.append(line)

# setup series
series = {} # dictionary
with open(data_path, "r") as f:
    for line in f:
        try:
            match = json.loads(line)
            # if (match["league_name"]+"\n") in tournament_list : # ensure the match is from a valid tournament
            series_id = match["series_id"]
            if series_id not in series:                     # if this is the first series, create array
                series[series_id] = []
            series[series_id].append(match)                 # and then append to the array

        except json.JSONDecodeError:
            continue


with open(output_path, "w") as f:

    for series_id in series:

        # ignore matches where series_id is invalid or not set
        if(series_id == 0):
            continue

        # check to see if the series contains a long match
        containsLongMatch = False
        for match in series[series_id]:     # series[series_id] is an array
            if(match["duration"] > 3600):
                containsLongMatch = True
            
        line = ""

        # output the match
        if containsLongMatch:
            line += f"{dota_helper.seriesToString(series[series_id])}\n"
            line += f"{dota_helper.epochToReadable(series[series_id][0]['start_time']):>50s} ||"

            for match in series[series_id]:
                line += f"{dota_helper.formatSeconds(match['duration']):<11s} "

            line += f"\n{'':>50s} || "
            for match in series[series_id]:
                line += f"{match['match_id']:<11d} "

            line += "\n\n"
  
            
        f.write(line)



print(f"{(process.memory_info().rss / 1000000):.1f} MB")  # in MB 
timeDelta = datetime.now() - startTime
print(f"{timeDelta} seconds")
