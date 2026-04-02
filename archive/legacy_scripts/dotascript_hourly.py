import json
import requests
import os
from datetime import datetime


year = datetime.now().year
file_path = f"/home/tankionlinefirstseargent/python/dotascript/data/{year}.jsonl"
log_file_path = f"/home/tankionlinefirstseargent/python/dotascript/log.txt"

# Create existing_ids, to check for duplicate matches
existing_ids = set()

if os.path.exists(file_path):
    with open(file_path, "r") as f: # open {year}.jsonl
        for line in f:
            try:
                match = json.loads(line)
                existing_ids.add(match["match_id"])
            except json.JSONDecodeError:
                continue

# API Call
url = "https://api.opendota.com/api/proMatches"
response = requests.get(url)

if response.status_code == 200:

    new_matches = response.json()
    
    unique_new_matches = []

    for match in new_matches:
        if match["match_id"] not in existing_ids: # 
            unique_new_matches.append(match)      # build a list of *new* unique matches

    unique_new_matches = sorted(unique_new_matches, key=lambda x: x["match_id"])

    if unique_new_matches:
        with open(file_path, "a") as f:
            for new_match in unique_new_matches:        # for each new_match a
                f.write(json.dumps(new_match) + "\n")   # append to file

        with open(log_file_path, "a") as log:           # write to log
            log.write(f"{datetime.now()}\tAdded {len(unique_new_matches)} new matches.\n")
    else:
        with open(log_file_path, "a") as log:           # write to log
            log.write(f"{datetime.now()}\tNo New Matches Added.\n")

else:
    with open(log_file_path, "a") as log:
        log.write(f"{datetime.now()}\tFAILED to Fetch Data:", response.status_code)

print("DONE")