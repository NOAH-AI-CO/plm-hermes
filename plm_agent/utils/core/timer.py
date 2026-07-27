import datetime
import time
import os


def async_timer(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs('logs', exist_ok=True)
        with open('logs/execution_time.log', 'a') as log_file:
            log_file.write(f"{current_time} {func.__name__} execution time: {end_time - start_time} seconds\n")
        return result
    return wrapper