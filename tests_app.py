import requests
import time

app_url = "http://localhost:8000/signin"

def test_app():
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get(app_url)
            if response.status_code == 200:
                print("App is up and running!")
                return
        except requests.exceptions.ConnectionError:
            print(f"Waiting for app to start... (Attempt {i+1}/{max_retries})")
        time.sleep(2)
        
    assert False, f"Unable to load Flask app after {max_retries * 2} seconds"
        