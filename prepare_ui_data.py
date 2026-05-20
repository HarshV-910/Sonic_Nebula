import pandas as pd
import numpy as np

def main():
    print("Loading raw music data...")
    raw_df = pd.read_csv('data/raw/Music_Info.csv')
    
    print("Loading track IDs...")
    track_ids = np.load('models/track_ids.npy', allow_pickle=True)
    
    # Filter only those that are in interaction matrix to avoid errors in collaborative filtering later
    flask_df = raw_df[raw_df['track_id'].isin(track_ids)].copy()
    
    print("Processing tags and genres into categories...")
    # Fill empty tags with empty string
    flask_df['tags'] = flask_df['tags'].fillna('')
    flask_df['genre'] = flask_df['genre'].fillna('')
    
    # Use the primary explicit genre column instead of text matching
    flask_df['primary_category'] = flask_df['genre'].apply(lambda x: str(x).title() if str(x).strip() else 'Other')
    
    # Fix explicit mappings to match user preferences if necessary
    flask_df['primary_category'] = flask_df['primary_category'].replace({'Rnb': 'RnB'})
    
    # We just need these cols for the UI index
    cols = ['track_id', 'name', 'artist', 'year', 'duration_ms', 'primary_category', 'spotify_preview_url', 'tags']
    flask_df = flask_df[cols]
    
    # Convert duration from ms to minute:second
    flask_df['duration'] = pd.to_datetime(flask_df['duration_ms'], unit='ms').dt.strftime('%M:%S')
    
    output_path = 'data/processed/Music_Info_flask.csv'
    flask_df.to_csv(output_path, index=False)
    print(f"Extraction complete! Saved processed data to {output_path} with {len(flask_df)} rows")

if __name__ == '__main__':
    main()
