#!/bin/bash

# Update system
sudo dnf update -y

# Install dependencies
sudo dnf install -y docker unzip curl

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add ec2-user to docker group
sudo usermod -aG docker ec2-user

# Install AWS CLI if not installed
cd /home/ec2-user

curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"

unzip -o awscliv2.zip

sudo ./aws/install

# Cleanup
rm -rf aws awscliv2.zip

# # Create swap only if not already exists
# if ! sudo swapon --show | grep -q "/swapfile"; then
#     sudo fallocate -l 2G /swapfile
#     sudo chmod 600 /swapfile
#     sudo mkswap /swapfile
#     sudo swapon /swapfile
# fi