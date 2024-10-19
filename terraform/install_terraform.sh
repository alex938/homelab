#!/bin/bash

# Step 1: Update package list and install dependencies
echo "Updating package list and installing required dependencies..."
sudo apt-get update
sudo apt-get install -y curl unzip

# Step 2: Download Terraform binary for Linux ARM64
echo "Downloading Terraform for Linux ARM64..."
TERRAFORM_VERSION="1.5.6"
wget https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_arm64.zip

# Step 3: Unzip the downloaded file
echo "Unzipping Terraform binary..."
unzip terraform_${TERRAFORM_VERSION}_linux_arm64.zip

# Step 4: Move Terraform binary to /usr/local/bin
echo "Installing Terraform..."
sudo mv terraform /usr/local/bin/

# Step 5: Cleanup
echo "Cleaning up downloaded files..."
rm terraform_${TERRAFORM_VERSION}_linux_arm64.zip

# Step 6: Verify the installation
echo "Verifying Terraform installation..."
terraform -v

if [ $? -eq 0 ]; then
  echo "Terraform has been installed successfully!"
else
  echo "There was an issue installing Terraform."
fi
