import os, requests
from dotenv import load_dotenv
 
load_dotenv()
key = os.environ['NASA_API_KEY']
 
r = requests.get('https://api.nasa.gov/planetary/apod', params={'api_key': key})
print(r.status_code, r.json()['title'])
