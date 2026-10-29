import datetime
import wikipedia
import requests
import webbrowser

def get_greeting():
    hour = datetime.datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 18:
        return "Good afternoon"
    else:
        return "Good evening"

def get_time():
    now = datetime.datetime.now()
    return now.strftime("%I:%M %p")

def get_date():
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y")

def get_time_and_date():
    return f"It's {get_time()} on {get_date()}."
