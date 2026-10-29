import requests

API_KEY = None

def get_weather(city):
    try:
        url = f"http://api.weatherapi.com/v1/current.json?key={API_KEY}&q={city}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if "error" in data:
            return f"I couldn't find weather data for {city}. Please check the city name."
        loc = data["location"]
        current = data["current"]
        return (
            f"Weather in {loc['name']}, {loc['country']}: "
            f"{current['condition']['text']}, "
            f"{current['temp_c']}C ({current['temp_f']}F), "
            f"Humidity: {current['humidity']}%, "
            f"Wind: {current['wind_kph']} km/h"
        )
    except Exception:
        return "I couldn't fetch the weather right now. Please try again later."
