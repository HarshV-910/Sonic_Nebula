# Sonic Nebula: Complete AWS Deployment & CI/CD Guide

This guide details the complete deployment pipeline for the Sonic Nebula project. It covers Data Version Control (DVC), GitHub Actions CI/CD pipeline setup, Dockerization via ECR, and automated deployments using AWS CodeDeploy to an Auto Scaling Group.

---

## 1. DVC (Data Version Control) Setup on S3

DVC manages your large datasets (`df_transformed.npz`, `interaction_matrix.npz`, etc.). We use an S3 bucket to store this data remotely.

1. **Create an S3 Bucket for DVC**:
   - Go to **S3** in the AWS Console.
   - Click **Create bucket**.
   - **Bucket name**: `sonic-nebula-dvc-bkt` (must be globally unique, you may need to append numbers if taken).
   - **Region**: `ap-southeast-2` (Sydney).
   - Leave other settings as default and click **Create bucket**.

2. **Configure DVC Locally** (Run in your terminal):
   ```bash
   aws configure  # Ensure AWS CLI is logged in
   dvc remote add -d myremote s3://sonic-nebula-dvc-bkt
   dvc push
   git add .dvc/config
   git commit -m "Configure DVC remote to sonic-nebula-dvc-bkt"
   git push
   ```

---

## 2. GitHub Actions Secrets & Dependencies

Your `.github/workflows/ci.yaml` pipeline requires permissions to push to ECR, upload zips to S3, and trigger CodeDeploy.

1. **Handling Dependencies (`requirements.txt`)**:
   To avoid version conflicts in the pipeline, generate your `requirements.txt` cleanly:
   ```bash
   pip install pip-tools
   # add basic libraries to requirements.in
   pip-compile requirements.in
   pip install -r requirements.txt
   ```

2. **Create an IAM User for GitHub Actions**:
   - Go to **IAM** -> **Users** -> **Create user**.
   - **Name**: `sonic-nebula-github-action-user`.
   - Attach policies directly: `AmazonS3FullAccess`, `AmazonEC2ContainerRegistryFullAccess`, `AWSCodeDeployFullAccess`.
   - Complete creation, then go to the User's **Security credentials** tab.
   - Create an **Access key** (Select "Third-party service").

3. **Add Secrets to GitHub Repo**:
   - Go to your GitHub Repository -> **Settings** -> **Secrets and variables** -> **Actions**.
   - Add `AWS_ACCESS_KEY_ID` (from step above).
   - Add `AWS_SECRET_ACCESS_KEY` (from step above).
   - Add `ECR_REPOSITORY_URI` (Value: `sonic-nebula-ecr` — the pipeline will automatically create the ECR for you if it doesn't exist).

---

## 3. Database Setup: DynamoDB

Your new Flask application uses DynamoDB for storing user accounts.

1. **Create DynamoDB Table**:
   - Go to **DynamoDB** in the AWS Console.
   - Click **Create table**.
   - **Table name**: `SonicNebulaUsers` (Exactly this name, case-sensitive).
   - **Partition key**: `username` (Type: String).
   - Leave table settings as Default and click **Create table**.

---

## 4. EC2 Instance Profile & IAM Roles

AWS CodeDeploy needs permissions to pull from S3 and manage EC2. Your EC2 instances need permissions to pull Docker images from ECR and read from DynamoDB.

1. **Create EC2 Role** (`sonic-nebula-ec2-role`):
   - Go to **IAM** -> **Roles** -> **Create role**.
   - Trusted entity: **AWS service** -> **EC2**.
   - Attach Policies: 
     - `AmazonEC2ContainerRegistryReadOnly` (To pull Docker images)
     - `AmazonS3ReadOnlyAccess` (To download CodeDeploy artifacts)
     - `AmazonDynamoDBFullAccess` (To allow the Flask app to read/write users)
   - **Role name**: `sonic-nebula-ec2-role`.

2. **Create CodeDeploy Service Role** (`sonic-nebula-codedeploy-role`):
   - Go to **IAM** -> **Roles** -> **Create role**.
   - Trusted entity: **AWS service** -> **CodeDeploy**.
   - Attach Policy: `AWSCodeDeployRole`.
   - **Role name**: `sonic-nebula-codedeploy-role`.

---

## 5. Compute Setup: Launch Template & Auto Scaling Group

We will use a Launch Template so AWS can automatically boot up identical EC2 instances when scaling.

1. **Create Launch Template**:
   - Go to **EC2** -> **Launch Templates** -> **Create launch template**.
   - **Name**: `sonic-nebula-template`.
   - **OS/AMI**: `Amazon Linux 2023 kernel-6.1 AMI` (64-bit x86, Free tier eligible).
   - **Instance type**: `t2.micro` (Free tier).
   - **Key pair**: Create a new key pair named `sonic-nebula-key` (download the `.pem` file).
   - **Security Group**: Create a new Security Group named `sonic-nebula-sg`.
     - Allow **SSH (Port 22)** from Anywhere.
     - Allow **Custom TCP (Port 8000)** from Anywhere (This is where the Docker container runs).
   - **Advanced Details**:
     - **IAM instance profile**: Select `sonic-nebula-ec2-role`.
     - **User data** (Paste this script to install Docker, setup Swap, and install the CodeDeploy Agent on boot):
       ```bash
       #!/bin/bash

       dnf update -y
       dnf install ruby wget docker unzip -y

       systemctl start docker
       systemctl enable docker

       usermod -aG docker ec2-user

       # Swap configuration (necessary for loading large ML matrices into memory)
       fallocate -l 2G /swapfile
       chmod 600 /swapfile
       mkswap /swapfile
       swapon /swapfile

       cd /home/ec2-user

       # Install CodeDeploy Agent for Amazon Linux
       wget https://aws-codedeploy-ap-southeast-2.s3.ap-southeast-2.amazonaws.com/latest/install
       chmod +x ./install
       ./install auto

       systemctl enable codedeploy-agent
       systemctl start codedeploy-agent
       ```

2. **Create Target Group & Load Balancer** (Optional but recommended for scaling):
   - Go to **Target Groups** -> **Create target group**.
     - Type: Instances. Name: `sonic-nebula-tg`. Port: 8000. Health Check Path: `/`.
   - Go to **Load Balancers** -> **Create Load Balancer** -> **Application Load Balancer**.
     - Name: `sonic-nebula-alb`. Internet-facing. Listen on Port 80.
     - Forward to `sonic-nebula-tg`.

3. **Create Auto Scaling Group (ASG)**:
   - Go to **Auto Scaling Groups** -> **Create Auto Scaling group**.
   - **Name**: `sonic-nebula-asg`.
   - Select the `sonic-nebula-template` you just created.
   - Select your VPC and subnets (choose multiple AZs like `ap-southeast-2a`, `ap-southeast-2b`).
   - Attach it to the existing load balancer (`sonic-nebula-tg`).
   - Group size: **Desired: 1, Min: 1, Max: 3**.
   - Target tracking policy: Average CPU utilization at 50%.

---

## 6. AWS CodeDeploy Configuration

CodeDeploy will take the `.zip` generated by GitHub Actions and deploy it to your EC2 instances seamlessly.

1. **Create S3 Deployment Bucket**:
   - Go to **S3** -> **Create bucket**.
   - **Name**: `hybrid-sys-deployment-bkt` (Must exactly match the bucket name in your `.github/workflows/ci.yaml`).
   - Region: `ap-southeast-2`.

2. **Create CodeDeploy Application**:
   - Go to **CodeDeploy** -> **Applications** -> **Create application**.
   - **Name**: `hybrid_sys_app` (Must exactly match your `ci.yaml`).
   - **Compute platform**: EC2/On-premises.

3. **Create Deployment Group**:
   - Inside `hybrid_sys_app`, click **Create deployment group**.
   - **Name**: `hybrid_sys_deployment_grp` (Must exactly match your `ci.yaml`).
   - **Service role**: Select `sonic-nebula-codedeploy-role`.
   - **Deployment type**: In-place.
   - **Environment configuration**: Select **Auto Scaling groups** and choose `sonic-nebula-asg`.
   - **Load balancer**: Enable load balancing and select `sonic-nebula-tg` (if using ALB), or uncheck if running a single instance without a load balancer.

---

## 7. Trigger the Deployment & Testing

Everything on AWS is now waiting for code!

1. Go to your local terminal where your repository is.
2. Ensure you have committed all changes (including your `appspec.yml`, `.github/workflows/ci.yaml`, and `deploy/scripts/`).
3. `git push origin main`.
4. Open your GitHub Repository -> **Actions** tab. You will see the pipeline running. It will:
   - Pull the DVC data from S3.
   - Test the application.
   - Build the Docker image and push it to ECR.
   - Zip the deployment scripts.
   - Upload them to `hybrid-sys-deployment-bkt`.
   - Trigger AWS CodeDeploy.
5. Once the GitHub Action completes successfully, go to **AWS CodeDeploy** -> **Deployments**. Ensure the deployment succeeded.
6. Go to **EC2** -> **Instances**. Find the instance created by your Auto Scaling Group.
7. Copy its **Public IPv4 address**.
8. Open your browser and navigate to: `http://<YOUR_EC2_IP>:8000` (or your Load Balancer DNS name).

---

## Appendix: Manual Docker & ECR Troubleshooting

If you ever need to manually pull and run the Docker image on a raw EC2 instance without CodeDeploy, follow these steps:

1. SSH into the instance.
2. Authenticate Docker to ECR:
   ```bash
   aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin <YOUR_ACCOUNT_ID>.dkr.ecr.ap-southeast-2.amazonaws.com
   ```
3. Pull the image:
   ```bash
   docker pull <YOUR_ACCOUNT_ID>.dkr.ecr.ap-southeast-2.amazonaws.com/sonic-nebula-ecr:latest
   ```
4. Run the container:
   ```bash
   docker run --name hybrid_sys -d -p 8000:8000 <YOUR_ACCOUNT_ID>.dkr.ecr.ap-southeast-2.amazonaws.com/sonic-nebula-ecr:latest
   ```
