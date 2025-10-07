import json
import requests
import os
from datetime import datetime
import dotascript_helper_methods as dota_helper


file_path = "data/dump.jsonl"
def append(last_match):
    with open(file_path, "a") as f:

        match_list = dota_helper.getProMatch(last_match).json()

        match_list = sorted(match_list, key=lambda x: x["match_id"], reverse=True)

        for match in match_list:
            f.write(json.dumps(match) + "\n")
            last_match = match["match_id"]

    return last_match  


last_match = dota_helper.getOldestMatch(file_path)
for i in range(0,97):
    last_match = append(last_match)
    print(last_match)