# Gitlab setup

### Create the following:

```
sudo nano /etc/fstab
add line
nas.batcave.local:/volume1/docker_volumes /mnt/docker_volumes nfs rw,sync,hard 0 0
```


```
/mnt/docker_volumes/gitlab/config
/mnt/docker_volumes/gitlab/data
/mnt/docker_volumes/gitlab/logs
```


/etc/letsencrypt/gitlab-credentials.ini 
```
dns_cloudflare_email = 
dns_cloudflare_api_key = 
```


./config/gitlab.rb
```
gitlab_rails['gitlab_shell_ssh_port'] = 4242
external_url 'http://gitlab.labkjunkie.org'
nginx['listen_port'] = 80
nginx['listen_https'] = false
letsencrypt['enable'] = false
```


sudo nano /etc/letsencrypt/copy-certs.sh
```
#!/bin/bash
CERT_DIR="/mnt/docker_volumes/gitlab/certs"
mv /etc/letsencrypt/live/gitlab.labjunkie.org/fullchain.pem $CERT_DIR/fullchain.pem
mv /etc/letsencrypt/live/gitlab.labjunkie.org/privkey.pem $CERT_DIR/privkey.pem
chmod 600 $CERT_DIR/*
docker exec <nginx_container_name> nginx -s reload
```
```
sudo chmod +x /etc/letsencrypt/copy-certs.sh
```

```
sudo certbot renew --deploy-hook "/etc/letsencrypt/copy-certs.sh"
sudo certbot renew --dry-run
```