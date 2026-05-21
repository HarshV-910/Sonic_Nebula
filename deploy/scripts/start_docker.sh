#!/bin/bash
# Login to AWS ECR
exec > /home/ec2-user/start_docker.log 2>&1

echo "Logging into ECR..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="ap-southeast-2"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# Login to ECR using AWS credentials
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ECR_URI}

echo "Pulling Docker Image..."
docker pull ${ECR_URI}/sonic-nebula-ecr:latest

echo "Checking Existing Container..."
if [ "$(docker ps -q -f name=sonic-nebula-container)" ]; then
    echo "Stopping Existing Container..."   
    docker stop sonic-nebula-container || true
fi
if [ "$(docker ps -aq -f name=sonic-nebula-container)" ]; then
    echo "Removing Existing Container..."
    docker rm sonic-nebula-container || true
fi

echo "Starting New Container..."
docker run -d -p 8000:8000 --name sonic-nebula-container ${ECR_URI}/sonic-nebula-ecr:latest

echo "Container Started Successfully."
