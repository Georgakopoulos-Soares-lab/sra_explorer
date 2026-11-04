# Production deployment (www.srascout.com)

How the app runs on the production VM. The database checklist is in [production.md](production.md).

## Layout

| Part | How it runs | Where |
| --- | --- | --- |
| Database | Docker container `pgvector-db` (`pgvector/pgvector:pg16`), database `srascout`, port 5432, restart policy `unless-stopped` | data in a Docker volume |
| Backend | systemd service `srascout-api`: uvicorn, 2 workers, `127.0.0.1:8000` | `/root/sra_explorer/backend` (`.venv`, settings in `.env`) |
| Frontend | static build served by nginx | `/root/sra_explorer/frontend/dist` |
| HTTPS | nginx + Let's Encrypt certificate (certbot, renewed by `certbot.timer`) | `/etc/nginx/sites-available/srascout`, `/etc/letsencrypt/live/www.srascout.com/` |

nginx serves the frontend at `/`, forwards `/api/...` to the backend (dropping the `/api` prefix, like the Vite dev proxy), and forwards `/v1/...` as-is for the public API. HTTP redirects to HTTPS; `srascout.com` and `www.srascout.com` share one certificate.

## Backend settings

`backend/.env` (not in git):

```
DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/srascout
CORS_ORIGINS=https://www.srascout.com,https://srascout.com
TRUST_FORWARDED_FOR=true
EMBEDDING_THREADS=4
```

The venv was built with Python 3.14 and the CPU build of torch (`pip install torch --index-url https://download.pytorch.org/whl/cpu`) before `requirements.txt`.

## Everyday commands

```bash
# Backend
systemctl status srascout-api
systemctl restart srascout-api
journalctl -u srascout-api -f

# Frontend: rebuild after changing frontend/ (nginx picks up dist/ immediately)
cd /root/sra_explorer/frontend && npm run build

# nginx
nginx -t && systemctl reload nginx

# Certificate
certbot certificates
certbot renew --dry-run
```

## Deploying a new version

```bash
cd /root/sra_explorer && git pull
cd backend && .venv/bin/pip install -r requirements.txt && systemctl restart srascout-api
cd ../frontend && npm install && npm run build
```

## Notes

- `frontend/package.json`, `tsconfig*.json` and `public/favicon.svg` are ignored by the root `.gitignore` (`*.json`, `*.svg`), so they only exist on this machine. Copy them into the repository (or loosen `.gitignore`) before deploying elsewhere.
- After loading new data, refresh the views so search and the statistics page see it: `REFRESH MATERIALIZED VIEW CONCURRENTLY study_facets; REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_fulltext; REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_attribute_values;` then `ANALYZE`. Home page counts and the statistics page are cached for a week; restart the API (`systemctl restart srascout-api`) after loading new data so the home page shows the new numbers.
- Port 5432 is published on all interfaces by the Docker container, so the database is reachable from the internet with the password. Restrict it to the importing machine (or `127.0.0.1`) once the import is done.
