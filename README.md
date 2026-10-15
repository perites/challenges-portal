# challenge portal

Small Flask app to catalog and host friends' challenge pages. Full spec: [SPEC.md](SPEC.md).

## Run locally

```
python -m venv .venv
.venv/Scripts/activate          # Linux: source .venv/bin/activate
pip install -r requirements.txt

flask --app app add-challenge cat-api "test challenge to work with api"
flask --app app create-admin <your-name>
flask --app app run --debug
```

Open http://localhost:5000. The `data/` folder (database, uploads, secret key) is created on first start.

## Challenges

Put the text in `challenges/<slug>.md`, then register it:

```
flask --app app add-challenge <slug> "<title>"
```

The newest challenge is shown by default.

## Other commands

```
flask --app app create-admin <name>      # create admin or promote existing user
flask --app app reset-password <name>
```

## Deploy (Linux VPS)

```
git clone <repo> /srv/portal && cd /srv/portal
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app add-challenge cat-api "test challenge to work with api"
.venv/bin/flask --app app create-admin <your-name>
```

`/etc/systemd/system/portal.service`:

```
[Unit]
Description=challenge portal
After=network.target

[Service]
User=www-data
WorkingDirectory=/srv/portal
ExecStart=/srv/portal/.venv/bin/gunicorn --preload -w 2 -b 127.0.0.1:8000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/caddy/Caddyfile` (Caddy gets the HTTPS certificate automatically):

```
portal.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

```
sudo chown -R www-data /srv/portal/data
sudo systemctl enable --now portal
sudo systemctl reload caddy
```

Backup: copy `/srv/portal/data`.
