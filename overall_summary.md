# Music Recommendation System: Overall Flow Summary

This document outlines the complete pipeline for the hybrid music recommendation system, combining content-based and collaborative filtering approaches. It explains the data flow, key datasets, transformations, and how recommendations are generated, including solutions to alignment and scaling issues.

## 1. Data Overview

### Raw Datasets
- **`user_data` (User Listening History)**:
  - Source: `data/raw/User_Listening_History.csv`
  - Shape: ~9.7 million rows × 3 columns (`user_id`, `track_id`, `playcount`)
  - Description: Records user interactions with songs, including play counts. Contains ~30k unique `track_id`s (songs that have been listened to by users).
  - Note: Sparse data (many users haven't listened to many songs), which is why cosine similarity is used for collaborative filtering.

- **`songs_data` (Music Info)**:
  - Source: `data/raw/Music_Info.csv`
  - Shape: ~50k rows × 21 columns (includes `track_id`, `name`, `artist`, `spotify_preview_url`, `tags`, `genre`, audio features like `danceability`, `energy`, etc.)
  - Description: Metadata and features for all songs in the catalog. Includes ~50k unique songs.

### Key Insight
- Only ~30k songs from `songs_data` have user interaction data in `user_data`. The rest (~20k) have no listening history, so they're excluded from collaborative filtering.

## 2. Content-Based Recommender

### Step 1: Data Cleaning (`clean_music_data`)
- **Input**: `songs_data` (~50k rows)
- **Process**:
  - Drop duplicates and null values.
  - Drop unique columns like `track_id`, `spotify_id`, `name`, `spotify_preview_url`, and `genre` (these can't be used for cosine similarity as they're identifiers or non-numeric).
  - Fill nulls in `tags` with 'no_tag'.
  - Convert `artist` to lowercase.
  - Convert `year` to category for encoding.
- **Output**: `df_cleaned` (~50k rows × cleaned columns, e.g., `artist`, `tags`, `year`, audio features).
- **Saved As**: `data/processed/df_cleaned.csv`

### Step 2: Data Transformation (`transformed_data`)
- **Input**: `df_cleaned`
- **Process**:
  - **Vectorization & Scaling**: Use `ColumnTransformer` to convert strings to numerical vectors:
    - `CountEncoder` (frequency encoding) on `year`.
    - `OneHotEncoder` on `artist`, `time_signature`, `key`.
    - `TfidfVectorizer` (TF-IDF) on `tags` (text column, with stop words removed, max_features from params.yaml).
    - `StandardScaler` on `duration_ms`, `loudness`, `tempo`.
    - `MinMaxScaler` on `danceability`, `energy`, `speechiness`, `acousticness`, `instrumentalness`, `liveness`, `valence`.
  - This creates dense numerical vectors for each song.
- **Output**: `transformed_data` (sparse CSR matrix, shape: 50k rows × ~8431 features).
- **Saved As**: `data/processed/df_transformed.npz` (sparse matrix) + `models/transformer.joblib` (fitted transformer).

### Step 3: Recommendation Generation
- **Input**: `song_name` (e.g., "Mr. Brightside")
- **Process**:
  - Find the song's row in `songs_data` by `name`.
  - Extract its vector from `transformed_data`.
  - Compute cosine similarity between this vector and all other vectors in `transformed_data` (dense matrix, so similarities are high, near 1.0).
  - Sort similarities in descending order using `np.argsort`.
  - Select top-k indices and retrieve corresponding songs from `songs_data`.
- **Output**: List of recommended songs with `name`, `artist`, `spotify_preview_url`.
- **Key Params**: `k` (number of recommendations, e.g., 10).

## 3. Collaborative-Based Recommender

### Step 1: Interaction Matrix Creation
- **Input**: `user_data` (~9.7M rows)
- **Process**:
  - Use Dask for handling large data (~60GB potential dense matrix).
  - Encode `user_id` and `track_id` to categorical codes (to handle large numbers of users).
  - Create sparse CSR matrix: rows = `track_id` (30k unique), columns = `user_id` (~970k unique), values = aggregated `playcount`.
  - Divide data into 9 chunks for processing.
- **Output**: `interaction_matrix` (sparse CSR matrix, shape: 30k tracks × 970k users).
- **Saved As**: `data/processed/interaction_matrix.npz` + `models/track_ids.npy` (array of 30k track_ids in encoded order).

### Step 2: Song Filtering (`filtered_songs_data`)
- **Input**: `songs_data` (~50k rows) + `track_ids` (30k from interaction matrix)
- **Process**: Filter `songs_data` to only include songs present in `track_ids` (i.e., songs with user interactions).
- **Output**: `filtered_songs_data` (~30k rows × 21 columns, same structure as `songs_data`).
- **Saved As**: `data/processed/collab_filtered.csv`

### Step 3: Recommendation Generation
- **Input**: `song_name`, `artist_name` (e.g., "Mr. Brightside" by "The Killers")
- **Process**:
  - Find the song's `track_id` in `filtered_songs_data`.
  - Get its encoded index in `track_ids` (position in interaction matrix).
  - Extract the song's vector from `interaction_matrix` (sparse, so similarities are low).
  - Compute cosine similarity between this vector and all other vectors in `interaction_matrix`.
  - Sort similarities in descending order.
  - Map back to original `track_id`s and retrieve songs from `filtered_songs_data`.
- **Output**: List of recommended songs with `name`, `artist`, `spotify_preview_url`.
- **Key Params**: `k` (number of recommendations).

## 4. Hybrid Recommender

### Overview
- Combines content-based and collaborative scores: `final_score = w1 * s1 + w2 * s2`, where `w1 + w2 = 1` (e.g., `w1=0.5`, `w2=0.5`).
- **Input**: `song_name`, `artist_name`, `k` (recommendations).
- **Challenge**: Content scores are over 50k songs, collaborative over 30k → shape mismatch (50k vs. 30k).

### Step 1: Score Computation
- **Content Scores (`s1`)**: Compute over full `songs_data` and `transformed_data` (50k songs).
- **Collaborative Scores (`s2`)**: Compute over `filtered_songs_data`, `track_ids`, and `interaction_matrix` (30k songs).

### Step 2: Alignment (Solving Problem 1)
- **Issue**: `s1` is sorted by original `songs_data` index; `s2` is sorted by lexical (alphabetical) `track_id` order from Dask encoding.
- **Solution**: Align `s1` to the `track_ids` order:
  - Create a mapping from `track_id` to index in `songs_data`.
  - Reindex `s1` to match `track_ids` sequence.
  - Now both `s1` and `s2` are aligned on the same 30k songs.

### Step 3: Normalization (Solving Problem 2)
- **Issue**: Content similarities are high (dense matrix); collaborative are low (sparse matrix).
- **Solution**: Apply min-max normalization to both `s1` and `s2` before combining:
  - `normalized_s = (s - min(s)) / (max(s) - min(s))` if range > 0, else all zeros.

### Step 4: Combination and Recommendation
- Compute `final_scores = w1 * normalized_s1 + w2 * normalized_s2`.
- Sort `final_scores` descending, select top-k indices.
- Map indices to `track_id`s, retrieve from `filtered_songs_data` (to preserve ranking).
- **Output**: List of recommended songs with `name`, `artist`, `spotify_preview_url`.

### Key Params
- `weight_content` (w1, e.g., 0.5)
- `weight_collaborative` (w2, e.g., 0.5)
- `k` (recommendations)

## 5. Additional Details
- **Cosine Similarity**: Used throughout due to sparse data (efficient for high-dimensional vectors).
- **Dask Usage**: For large `user_data` processing to avoid memory issues.
- **Sparse Matrices**: `transformed_data` and `interaction_matrix` are saved as `.npz` for efficiency.
- **Error Handling**: Hybrid checks for shape mismatches, missing track_ids, and duplicate track_ids.
- **Streamlit App**: Loads all datasets and provides UI for selecting recommendation type.

This flow ensures scalable, accurate recommendations by leveraging both song features and user behavior.

## 6. Additional Insights and Optimizations

### Recommendation Strategies
- **Dynamic Recommendations**: To make suggestions more dynamic and based on what others like, we increase the collaborative weight (focus more on user behavior patterns).
- **Personalized Recommendations**: For more personalized results based on the song's features, we increase the content weight (focus more on the music's characteristics).

### Handling Song Data
- We have information for about 50,000 songs in total. However, only 30,000 of these have user listening data. This means:
  - The 30,000 songs with user data can use all types of recommendations (content-based, collaborative, and hybrid).
  - The remaining 20,000 songs (without user data) can only use content-based recommendations, as there's no collaborative information available.

### User-Based Approach
- **New Users**: Since they don't have listening history, we use content-based recommendations to suggest songs similar to their selected one.
- **Existing Users**: For users with past listening data, we use the hybrid approach to combine both content and collaborative methods for better results.

### Streamlit Performance
- Streamlit reruns the entire script every time a user changes an option (like selecting a song or clicking a button), which can be slow if loading large datasets each time.
- To fix this, we load and store the datasets only once during the first run, using caching to keep them in memory for faster access.

### Evaluation Metrics
- Common metrics for evaluating recommendation systems are precision (how many recommended items are relevant) and recall (how many relevant items are recommended).
- However, we don't use these here because we don't have labeled data (ground truth about what users actually like or dislike). Instead, we rely on the system's logic and user feedback for improvements.

---

## 7. CI / CD and Deployment Notes

### CI: DVC Pipeline -> GitHub Actions Runner -> Test

- Use S3 bucket for DVC remote and push artifacts.

Commands:

```bash
aws configure
dvc remote add -d myremote s3://hybrid-recsys-remote-bkt
dvc push
git add/commit/push
```

To create `requirements.txt` without version conflict, first create `requirements.in`, add basic library names, and then run this (takes time):

```bash
pip install pip-tools
touch requirements.in  # add libraries names in this file
pip-compile requirements.in
pip install -r requirements.txt
```

### CD

- Flow: all code -> docker img -> push on AWS ECR

To create Docker image:

```bash
docker build -t hybrid_sys:test . # to build img
docker run --name hybrid_sys -d -p 8000:8000 hybrid_sys:test # to run img

docker ps # to check running container
docker stop <container_id> # to Stop a running container (
docker image -a # to show all images
docker rmi <img_id> # to Delete an image
docker container prune -y # to Delete all exited container
```

Then:

- Check streamlit app on `localhost:8000`.
- Create ECR at AWS, e.g., `hybrid_sys_ecr`.
- Open that ECR and use push commands and use in `ci.yaml` file.

Now use commands of ECR for checking:

- First command: for login same.
- Last command: of push but change `push -> pull`.
- Then copy name of img by: `docker image ls -a`.
- Then docker run command given above:
  `docker run --name hybrid_sys_ecr -d -p 8000:8000 <copied_name with tag latest>`.
- Now check `localhost:8000` for streamlit app.

### Pulling on Single EC2 Instance

Now for this pulling we create EC2 instance on AWS:

1. Create role:
   - Create role with EC2 permissions.
   - Policy: `AmazonEC2ContainerRegistryFullAccess`.
   - Name: `hybrid_sys_ec2_ecr_role`.

2. Launch EC2:
   - Create instance name: `hybrid_sys_ec2`.
   - Server: ubantu.
   - Instance type: `t2.micro`.
   - keypair.
   - security_grp: add all TCP. like launch wizard-4
   - advance: add role: `hybrid_sys_ec2_ecr_role`.

3. Install Docker on it:

```bash
sudo apt-get update -y
sudo apt-get install -y docker.io
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ubuntu
```

4. Install awscli:

```bash
sudo apt-get install -y unzip curl
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/home/ubuntu/awscliv2.zip"
unzip -o /home/ubuntu/awscliv2.zip -d /home/ubuntu/
sudo /home/ubuntu/aws/install

rm -rf /home/ubuntu/awscliv2.zip /home/ubuntu/aws
newgrp docker
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

5. Authenticate by aws configure:

```bash
aws configure
```

6. Connect docker with ecr & pull & run:

```bash
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 252312374343.dkr.ecr.ap-southeast-2.amazonaws.com

docker pull 252312374343.dkr.ecr.ap-southeast-2.amazonaws.com/hybrid_sys_ecr:latest

docker run --name hybrid_sys_ecr -d -p 8000:8000 252312374343.dkr.ecr.ap-southeast-2.amazonaws.com/hybrid_sys_ecr:latest
```

Problem:

- streamlit not compatible with EC2, songs preview is https and we run on http.

Summary:

- pull docker img -> run app on single EC2(docker install,pull img from ECR, container runn, live app)

### CodeDeploy: Inplace Deployment

1. Auto Scaling Group by launch template (1 to 3 EC2) -> code deployment application -> deployment grp -> start deployment.

- create `hybrid_sys_ec2_codedeploy_role` and give permission: s3readonly, containerfullaccess, AWSCodeDeployFullAccess,AmazonEC2RoleforAWSCodeDeploy.

- create launch template:
  - name: `hybrid_sys_template`
  - version: latest
  - quickstart os: ubuntu
  - instance_type: t2.micro
  - key_pair: `hybrid_sys_keypair`
  - security_grp: `launch-wizard-4`
  - advnce role: `hybrid_sys_ec2_codedeploy_role`
  - user_data (script to install codedeploy agent on each machine):

```bash
#!/bin/bash
sudo apt update -y
sudo apt install ruby-full -y
sudo apt install wget -y
cd /home/ubuntu
wget https://aws-codedeploy-ap-southeast-2.s3.ap-southeast-2.amazonaws.com/latest/install
chmod +x ./install
sudo ./install auto
sudo systemctl start codedeploy-agent
```

- create auto-scaling-grp:
  - name: `hybrid_sys_asg1`
  - template: `hybrid_sys_template`
  - availability_zone: ap-southeast-2a & ap-southeast-2b
  - load_balancer: attach_a_new_balancer
  - load_balancer_name: `hybrid-sys-elb1`
  - scheme: internet_facing
  - port: 8000
  - target_grp: new: `hybrid-sys-targetgrp`
  - health_check: elb health check
  - max: 3
  - target_tracking_policy: avg. cpu utilization on 50%
  - additional: metrics collection within CloudWatch

- create service role for deployment group:
  - usecase: codedeploy
  - name: `hybrid_sys_codedeploy_service_role`

- code_deploy create application:
  - name: `hybrid_sys_app`
  - compute: ec2
  - create deployment grp: `hybrid_sys_deployment_grp1`
  - role: `hybrid_sys_codedeploy_service_role`
  - type: Blue/Green
  - selectasg: `hybrid_sys_asg1`
  - load-balancer: application load balancer: `hybrid-sys-targetgrp`

- create deployment s3 bucket: name: `hybrid-sys-deployment-bkt`

- write `appspec.yml`

2. some change in streamlit app

