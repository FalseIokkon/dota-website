import json
import requests
from datetime import datetime


def getOldestMatch(filepath):
    oldest_match = 18303775162
    
    with open(filepath, "r") as f:

        for line in f:
            try:
                match = json.loads(line)
                if(match["match_id"] < oldest_match):
                    oldest_match = match["match_id"]
            except json.JSONDecodeError:
                print("Error")
                continue

    return oldest_match

def getProMatch(last_match):

    url = "https://api.opendota.com/api/proMatches"

    headers = {
        "Authorization": "Bearer YOUR_API_KEY"
    }
    params = {
        "less_than_match_id": last_match
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        print("Failed:", response.status_code)
        return -1

    return response

def epochToReadable(epoch):
    return datetime.fromtimestamp(epoch).strftime("%b %d %Y %H:%M:%S")

def formatSeconds(t_seconds):
    minutes = t_seconds // 60
    if minutes < 60:
        first_digit = str(minutes)[0]
        return f" {first_digit}x:xx"
    elif minutes >= 60 and minutes < 100 :
        first_digit = str(minutes)[0]
        return f" {first_digit}x:xx"
    else:
        first_digit = str(minutes)[0]
        return f"{first_digit}xx:xx"

def matchToString(match):
    return f"\t{match["match_id"]} | {formatSeconds(match["duration"])} | {epochToReadable(match["start_time"])} - {match["league_name"]} {match["radiant_name"]} vs {match["dire_name"]}"


def seriesToString(series):
    return f"{series[0]["league_name"]:>50s} || {series[0]["radiant_name"]} vs {series[0]["dire_name"]}"
