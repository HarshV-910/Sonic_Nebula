import os
from googleapiclient.discovery import build

def get_api_key():
    # First try environment variable
    env_key = os.environ.get('YOUTUBE_API_KEY')
    if env_key:
        return env_key
        
    # Fallback to local file
    key_path = os.path.join(os.path.dirname(__file__), '..', 'keys.txt')
    try:
        with open(key_path, 'r') as f:
            for line in f:
                if line.startswith('YOUTUBE_API_KEY='):
                    return line.split('=', 1)[1].strip()
    except Exception as e:
        print(f"Error reading keys.txt: {e}")
    return None

YOUTUBE_API_KEY = get_api_key()
_youtube_client = None

def get_youtube_client():
    global _youtube_client
    if _youtube_client is not None:
        return _youtube_client
    
    if YOUTUBE_API_KEY:
        try:
            # We initialize statically using build_from_document to avoid network timeouts on cold boot? 
            # Or just build lazily so if it fails, it only fails the request, not the whole app.
            _youtube_client = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
            return _youtube_client
        except Exception as e:
            print(f"Failed to initialize YouTube API client: {e}")
            return None
    else:
        print("Warning: YouTube API Key not found.")
        return None

def search_youtube_video(song_name, artist_name):
    """
    Searches YouTube for the best video matching the song name and artist.
    Returns a dict with video_id and thumbnail_url, or None if not found or API fails.
    """
    youtube = get_youtube_client()
    if not youtube:
        return None

    query = f"{song_name} {artist_name} official audio"
    try:
        request = youtube.search().list(
            q=query,
            part='snippet',
            maxResults=1,
            type='video'
        )
        response = request.execute()
        
        items = response.get('items', [])
        if not items:
            return None
        
        best_item = items[0]
        video_id = best_item['id']['videoId']
        
        # Get highest resolution thumbnail available
        thumbnails = best_item['snippet']['thumbnails']
        thumbnail_url = thumbnails.get('high', thumbnails.get('medium', thumbnails.get('default')))['url']
        
        return {
            'video_id': video_id,
            'thumbnail_url': thumbnail_url,
            'title': best_item['snippet']['title']
        }
    except Exception as e:
        print(f"YouTube API Error searching for {query}: {e}")
        return None

def global_search_youtube(query, max_results=10):
    """
    Searches YouTube for a generic text query.
    Returns a list of dicts with video_id, thumbnail_url, and title.
    """
    youtube = get_youtube_client()
    if not youtube:
        return []

    try:
        request = youtube.search().list(
            q=query,
            part='snippet',
            maxResults=max_results,
            type='video'
        )
        response = request.execute()
        
        results = []
        for item in response.get('items', []):
            video_id = item['id'].get('videoId')
            if not video_id:
                continue
            thumbnails = item['snippet']['thumbnails']
            thumbnail_url = thumbnails.get('high', thumbnails.get('medium', thumbnails.get('default')))['url']
            title = item['snippet']['title']
            results.append({
                'video_id': video_id,
                'thumbnail_url': thumbnail_url,
                'title': title
            })
        return results
    except Exception as e:
        print(f"YouTube API Error querying '{query}': {e}")
        return []
