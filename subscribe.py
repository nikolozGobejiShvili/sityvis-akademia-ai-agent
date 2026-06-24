import requests

token = "EAAX20ZBJgFZCgBRZANyFHuI9OUN9eC9tHpldkih7dQGVbU7erTjCPta3FOZAiQvwi1DkmCJ94ZC5avjwijRtjkjhDgjyZC2pzBqKcDJfxKHd9bZCRMzzie3nSShWBrW8RrVL7MbyVZApH80EigEepXF9MLaH16mZCejyy6ZCzcZBafbe7Hq7D0vfcXkJCZCvkmL0Ng8NLv8wFmQgKbijZBnZBEmQySVuO1twZDZ"  # .env-დან

r = requests.post(
    "https://graph.facebook.com/v19.0/986476147893240/subscribed_apps",
    data={
        "subscribed_fields": "feed,messages",
        "access_token": token
    }
)
print(r.json())