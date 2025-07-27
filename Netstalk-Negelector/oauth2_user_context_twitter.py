import os
import json
import requests
import webbrowser
import urllib.parse
import time  
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# CHANGE EVERYTHING THAT HAVE "CHANGE THIS" TAG

TWITTER_CLIENT_ID = "YOUR-TWITTER-CLIENT-ID-HERE" # CHANGE THIS
TWITTER_CLIENT_SECRET = "YOUR-TWITTER-CLIENT-SECRET" # CHANGE THIS
REDIRECT_URI = "http://localhost:8888/callback" # DON'T CHANGE THIS
SCOPES = ['https://www.googleapis.com/auth/drive.file'] # DON'T CHANGE THIS
GOOGLE_CREDENTIALS_FILE = 'credentials.json' # DON'T CHANGE THIS
FOLDER_NAME = "YOUR-GOOGLE-DRIVE-FOLDER-NAME-HERE" # CHANGE THIS

# ------------------- TWITTER AUTH -------------------

def twitter_oauth2_user_context():
    auth_url = "https://twitter.com/i/oauth2/authorize"
    token_url = "https://api.twitter.com/2/oauth2/token"

    scope = "tweet.read users.read like.read offline.access"
    state = "state"

    params = {
        "response_type": "code",
        "client_id": TWITTER_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": scope,
        "state": state,
        "code_challenge": "challenge",
        "code_challenge_method": "plain"
    }

    url = f"{auth_url}?{urllib.parse.urlencode(params)}"
    print("[+] Opening browser for Twitter login...")
    webbrowser.open(url)

    redirect_response = input("[?] Paste the full redirect URL after login: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_response).query)['code'][0]

    data = {
        "grant_type": "authorization_code",
        "client_id": TWITTER_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": "challenge",
        "code": code
    }

    response = requests.post(token_url, data=data, auth=(TWITTER_CLIENT_ID, TWITTER_CLIENT_SECRET))
    response.raise_for_status()
    token_json = response.json()
    return token_json['access_token']

# ------------------- GOOGLE DRIVE AUTH -------------------

def authenticate_google_drive():
    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    return build('drive', 'v3', credentials=creds)

# ------------------- GOOGLE DRIVE UPLOAD -------------------

def upload_file(service, file_path, folder_id):
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, mimetype='image/png')
    service.files().create(body=file_metadata, media_body=media, fields='id').execute()

def create_or_get_folder(service, folder_name):
    results = service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)").execute()
    items = results.get('files', [])
    if items:
        return items[0]['id']
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    folder = service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

# ------------------- TWITTER IMAGE DOWNLOAD -------------------

def fetch_liked_tweets(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    user_response = requests.get("https://api.twitter.com/2/users/me", headers=headers)
    user_id = user_response.json()['data']['id']

    tweet_url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets?expansions=attachments.media_keys&media.fields=url"
    response = requests.get(tweet_url, headers=headers)
    if response.status_code != 200:
        raise Exception("Twitter API error:\n" + response.text)
    return response.json()

def download_images(tweet_data):
    media = tweet_data.get("includes", {}).get("media", [])
    downloaded_files = []

    for i, item in enumerate(media):
        if item['type'] == 'photo':
            url = item['url']
            response = requests.get(url)
            filename = f"tweet_image_{i}.png"
            with open(filename, 'wb') as f:
                f.write(response.content)
            downloaded_files.append(filename)
    return downloaded_files

# ------------------- MAIN -------------------

if __name__ == "__main__":
    from googleapiclient.http import MediaFileUpload

    print("[+] Authenticating Twitter...")
    twitter_token = twitter_oauth2_user_context()

    print("[+] Authenticating Google Drive...")
    drive_service = authenticate_google_drive()
    folder_id = create_or_get_folder(drive_service, FOLDER_NAME)

    print("[+] Fetching liked tweets...")
    tweet_data = fetch_liked_tweets(twitter_token)

    print("[+] Downloading images...")
    image_files = download_images(tweet_data)

    if not image_files:
        print("[-] No images found.")
    else:
        print("[+] Uploading to Google Drive...")
        for file in image_files:
            upload_file(drive_service, file, folder_id)
            print(f"Uploaded {file}")
            os.remove(file)

        print("[✔] All done! Images are in your Google Drive folder.")

# ------------------- DELAY--------------------
def fetch_liked_tweets_with_media(bearer_token, user_id, max_pages=5):
    headers = {
        "Authorization": f"Bearer {bearer_token}"
    }
    tweets = []
    url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets?expansions=attachments.media_keys&media.fields=type,url&max_results=100"

    for _ in range(max_pages):  # Limit to avoid hitting rate limit
        response = requests.get(url, headers=headers)

        if response.status_code == 429:
            print("[!] Rate limit hit. Waiting 15 minutes before retrying...")
            time.sleep(15 * 60)  # Sleep for 15 minutes
            continue

        elif response.status_code != 200:
            print(f"[!] Twitter API error: {response.text}")
            break

        data = response.json()
        tweets.extend(data.get("data", []))

        # Handle pagination
        meta = data.get("meta", {})
        next_token = meta.get("next_token")
        if not next_token:
            break

        # Append next token to URL for next request
        url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets?pagination_token={next_token}&expansions=attachments.media_keys&media.fields=type,url&max_results=100"

        # Sleep to avoid rate-limiting
        print("[*] Sleeping for 3 seconds to avoid rate limit...")
        time.sleep(3)

    return tweets
