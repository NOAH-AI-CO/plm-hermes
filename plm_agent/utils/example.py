def get_weather(city, date):
    """
    Get weather information of the city and date.
    """
    weather_data = {
        "Beijing": { "2024-09-30": {"Temperature":"20 Celsius", "Type": "Sunny", "Wind": "3m/s"},
                        "2024-10-01": {"Temperature":"23 Celsius", "Type": "Cloudy", "Wind": "4m/s"},
                        "2024-10-02": {"Temperature":"24 Celsius", "Type": "Sunny", "Wind": "5m/s"}},
        "Shanghai": { "2024-09-30": {"Temperature":"22 Celsius", "Type": "Sunny", "Wind": "3m/s"},
                        "2024-10-01": {"Temperature":"25 Celsius", "Type": "Cloudy", "Wind": "4m/s"},
                        "2024-10-02": {"Temperature":"26 Celsius", "Type": "Sunny", "Wind": "5m/s"}},
    }
    if city in weather_data and date in weather_data[city]:
        return weather_data[city][date]
    return "No weather information found for the city and date."

def get_name_meaning(name):
    """
    Get name information.
    """
    name_data = {
        "Amanda":"Cool",
        "Bob":"Kind",
        "Cathy":"Smart",
    }
    if name in name_data:
        return name_data[name]
    return "No name information found"