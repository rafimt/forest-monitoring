# Step 5: Deploy to Streamlit Community Cloud

## Goal

Put the app online for free. Two things must move off your laptop:
1. The **database** → a cloud PostGIS (local Docker on port 5435 isn't reachable from the web).
2. **Earth Engine auth** → a **service account** (the server can't do interactive browser login).

The code already supports both via `st.secrets` (see `app/config.py`, `app/gee.py`).

---

## Part A — Cloud PostGIS

Use a managed Postgres that supports PostGIS. Free options: **Supabase**, **Neon**.

### 1. Create the database
- **Supabase:** New project → it includes PostGIS. Get the connection string from
  Project Settings → Database → Connection string (URI).
- Note the URL: `postgresql://USER:PASSWORD@HOST:5432/postgres`

### 2. Enable PostGIS + create the schema
In the Supabase SQL editor (or `psql`), run the contents of `db/init.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
-- ... the aoi + ndvi_series tables ...
```

### 3. Load your data into the cloud DB
Point the ingest at the cloud DB and re-run it locally:
```bash
# temporarily set the cloud URL, then ingest
set DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres   # Windows
python -m app.ingest_ndvi
```
This computes and stores all AOIs + indices in the cloud database.

> Alternatively, `pg_dump` your local DB and restore into the cloud one.

---

## Part B — GEE Service Account

Interactive `earthengine authenticate` can't run on a server. Use a service account.

### 1. Create it
- Go to https://console.cloud.google.com → project `rmtumon` → IAM & Admin → Service Accounts
- **Create service account** (e.g. `ee-runner`) → create a **JSON key** → download it.

### 2. Register it for Earth Engine
- At https://code.earthengine.google.com → project settings, or via
  https://signup.earthengine.google.com/, **register the service account email** for EE access.
- The email looks like `ee-runner@rmtumon.iam.gserviceaccount.com`.

### 3. You now have
- `GEE_SERVICE_ACCOUNT` = that client_email
- `GEE_KEY_JSON` = the full contents of the downloaded JSON key

`app/gee.py` uses these automatically when present (falls back to interactive auth locally).

---

## Part C — Deploy

### 1. Push to GitHub (done)
Repo: https://github.com/rafimt/forest-monitoring

### 2. Create the Streamlit app
- Go to https://share.streamlit.io → **New app**
- Repo: `rafimt/forest-monitoring`, branch: `main`
- **Main file path:** `app/view.py`

### 3. Add secrets
In the app's **Advanced settings → Secrets**, paste (see `.streamlit/secrets.toml.example`):
```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/postgres"
GEE_PROJECT = "rmtumon"
GEE_SERVICE_ACCOUNT = "ee-runner@rmtumon.iam.gserviceaccount.com"
GEE_KEY_JSON = '''
{ ...full service account JSON... }
'''
```

### 4. Deploy
Click **Deploy**. Streamlit installs `requirements.txt` and runs `app/view.py`.

> **Note on the geo stack:** Streamlit Cloud runs Linux, where `pip install` gets binary
> wheels for geopandas/fiona/rasterio without the Windows ordering dance — `requirements.txt`
> just works. The compiled geo libs are already pinned there.

---

## Part D — The viewer needs no GEE

`app/view.py` only **reads from PostGIS** — it never calls Earth Engine. So for a pure viewer
deployment you technically only need `DATABASE_URL`. GEE secrets are needed only if you also
run ingest/compute from the deployed app. Since ingest is a local script, the deployed viewer
can run on the database alone.

**Minimal viewer secrets:**
```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/postgres"
```

---

## What Success Looks Like
- App loads at `https://<your-app>.streamlit.app`
- AOI + index dropdowns work
- Map + chart render from the cloud database
- (If ingest on server) GEE compute works via the service account

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `could not connect` to DB | Wrong/blocked URL | Use the cloud URL; ensure the DB allows external connections |
| `no such table` | Schema not created in cloud DB | Run `db/init.sql` there, then ingest |
| EE permission error on server | Service account not registered for EE | Register the account email for Earth Engine |
| Geo libs fail to build | (rare on Linux) | They ship Linux wheels; keep versions from `requirements.txt` |
| Secrets not picked up | Wrong key names | Match `DATABASE_URL`, `GEE_PROJECT`, etc. exactly |
