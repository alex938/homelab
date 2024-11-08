# Gitlab Setup

### Create/setup the following:

1. Edit `/etc/fstab` to add the NFS mount:
    ```sh
    sudo nano /etc/fstab
    ```
    Add the following line:
    ```
    nas.batcave.local:/volume1/docker_volumes /mnt/docker_volumes nfs rw,sync,hard 0 0
    ```
2. Create the necessary directories:
    ```sh
    mkdir -p /mnt/docker_volumes/gitlab/config
    mkdir -p /mnt/docker_volumes/gitlab/data
    mkdir -p /mnt/docker_volumes/gitlab/logs
    mkdir -p /mnt/docker_volumes/gitlab/certs/live/gitlab.labjunkie.org
    ```

3. Configure Let's Encrypt credentials in `/etc/letsencrypt/gitlab-credentials.ini`:
    ```
    dns_cloudflare_email = 
    dns_cloudflare_api_key = 
    ```

4. Configure Gitlab in `./config/gitlab.rb`:
    ```ruby
    gitlab_rails['gitlab_shell_ssh_port'] = 4242
    external_url 'http://gitlab.labkjunkie.org'
    nginx['listen_port'] = 80
    nginx['listen_https'] = false
    letsencrypt['enable'] = false
    ```

5. Create the script to copy certificates:
    ```sh
    sudo nano /etc/letsencrypt/copy-certs.sh
    ```
    Add the following content:
    ```bash
    #!/bin/bash
    CERT_DIR="/mnt/docker_volumes/gitlab/certs/live/gitlab.labjunkie.org"
    mv /etc/letsencrypt/live/gitlab.labjunkie.org/fullchain.pem $CERT_DIR/fullchain.pem
    mv /etc/letsencrypt/live/gitlab.labjunkie.org/privkey.pem $CERT_DIR/privkey.pem
    chmod 600 $CERT_DIR/*
    docker exec <nginx_container_name> nginx -s reload
    ```

6. Make the script executable:
    ```sh
    sudo chmod +x /etc/letsencrypt/copy-certs.sh
    ```

7. Set up Certbot to renew certificates and run the script:
    ```sh
    sudo certbot renew --deploy-hook "/etc/letsencrypt/copy-certs.sh"
    sudo certbot renew --dry-run --deploy-hook "/etc/letsencrypt/copy-certs.sh"
    ```

8. Install Certbot DNS Cloudflare plugin and obtain certificates:
    ```sh
    sudo apt install python3-certbot-dns-cloudflare

    sudo certbot certonly \
      --dns-cloudflare \
      --dns-cloudflare-credentials /etc/letsencrypt/credentials.ini \
      -d gitlab.labjunkie.org \
      --deploy-hook "/etc/letsencrypt/copy-certs.sh"
    ```