# Deploy

Reference templates for the production install on a Linux VPS with
nginx + Let's Encrypt + systemd. The current target is one OVH VPS,
but the templates have no OVH-specific bits.

## Prerequisites on the VPS

```sh
sudo apt update
sudo apt install -y \
    python3-pip python3-venv \
    gdal-bin libgdal-dev \
    pdal libpdal-dev \
    nginx \
    certbot python3-certbot-nginx
```

## Layout assumed by the templates

```
/var/helios-lidar/
|-- app/                      # checked out from this repo
|-- .venv/                    # python venv with the project + deps
|-- frontend/                 # copy of frontend/ from this repo
|-- jobs/                     # incoming uploads (cleaned daily)
`-- output/                   # finished COGs (cleaned monthly)
```

Owned by the `helios-lidar` system user; group `helios-lidar`.

## One-shot install

```sh
# 1. system user + directories
sudo useradd -r -m -d /var/helios-lidar -s /usr/sbin/nologin helios-lidar
sudo install -d -o helios-lidar -g helios-lidar -m 750 \
    /var/helios-lidar/{app,jobs,output,frontend}

# 2. checkout + venv
sudo -u helios-lidar git clone https://github.com/ReikanYsora/Helios-Lidar.git /var/helios-lidar/app
sudo -u helios-lidar python3 -m venv /var/helios-lidar/.venv
sudo -u helios-lidar /var/helios-lidar/.venv/bin/pip install -e /var/helios-lidar/app

# 3. frontend
sudo -u helios-lidar cp -r /var/helios-lidar/app/frontend/* /var/helios-lidar/frontend/

# 4. systemd unit
sudo cp /var/helios-lidar/app/deploy/helios-lidar.service.example \
    /etc/systemd/system/helios-lidar.service
sudo systemctl daemon-reload
sudo systemctl enable --now helios-lidar

# 5. nginx vhost
sudo cp /var/helios-lidar/app/deploy/nginx-vhost.conf.example \
    /etc/nginx/sites-available/helios-lidar
sudo ln -sf /etc/nginx/sites-available/helios-lidar \
    /etc/nginx/sites-enabled/helios-lidar
sudo nginx -t && sudo systemctl reload nginx

# 6. HTTPS
sudo certbot --nginx -d helios-lidar.org -d www.helios-lidar.org

# 7. cleanup cron
sudo cp /var/helios-lidar/app/deploy/cleanup.cron.example \
    /etc/cron.d/helios-lidar-cleanup
```

## Updating

```sh
sudo -u helios-lidar git -C /var/helios-lidar/app pull
sudo -u helios-lidar /var/helios-lidar/.venv/bin/pip install -e /var/helios-lidar/app
sudo systemctl restart helios-lidar
```

## Logs

```sh
journalctl -u helios-lidar -f                 # app
tail -F /var/log/nginx/access.log /var/log/nginx/error.log
```
