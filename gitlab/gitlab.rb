gitlab_rails['gitlab_shell_ssh_port'] = 4242
external_url 'http://gitlab.labkjunkie.org'
nginx['listen_port'] = 80
nginx['listen_https'] = false
letsencrypt['enable'] = false