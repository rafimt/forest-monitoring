# Deployment Log — What We Actually Did

The real, step-by-step record of deploying the viewer to Streamlit Community Cloud with a
Supabase PostGIS backend, including the problems hit and how each was fixed.

**Live app:** Streamlit Cloud · **Repo:** https://github.com/rafimt/forest-monitoring
**Database:** Supabase (PostGIS)

---

## The architecture we deployed

```
Streamlit Cloud (app/view.py)  ──reads──►  Supabase PostGIS  (aoi, ndvi_series)
        (viewer only)                          ▲
                                                │ loaded once, locally
                        local machine: python -m app.ingest_ndvi
                        (Earth Engine compute → writes to Supabase)
```

Key idea: **the deployed app only reads the database.** All Earth Engine computation happens
locally in the ingest script; the cloud app never touches GEE.

---

## Step 1 — Supabase database

1. Created a Supabase project (includes PostGIS).
2. Enabled the extension in the SQL editor:
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```
3. Created the tables by running `db/init.sql` against Supabase.

### Gotcha: use the **Session pooler** connection string, not Direct
- The **Direct** string (`db.<ref>.supabase.co:5432`) is **IPv6-only** on the free tier and
  failed to resolve from our network (`could not translate host name`).
- The **Session pooler** string works over IPv4:
  ```
  postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres
  ```
  Note the user is `postgres.<project-ref>` and the host is `...pooler.supabase.com`.

---

## Step 2 — Load data into Supabase

Pointed the ingest at the cloud DB (env var overrides `.env`) and ran it locally:

```bash
set DATABASE_URL=postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres
python -m app.ingest_ndvi
```

This computed all indices via Earth Engine and wrote the 4 AOIs + monthly series to Supabase.
Verified with a `COUNT(*)` join query.

---

## Step 3 — Make the code deployment-ready

`app/config.py` reads config from **Streamlit secrets first, then `.env`**:

```python
def _get(key, default=None):
    if st is not None:
        try:
            val = st.secrets[key]          # direct access; KeyError if absent
            if val is not None:
                return val
        except Exception:
            pass
    return os.getenv(key, default)
```

So the **same code** uses local Docker on the laptop and Supabase on the cloud — no branching.

---

## Step 4 — Deploy on Streamlit Cloud

1. https://share.streamlit.io → **Create app** → from GitHub.
2. Repo `rafimt/forest-monitoring`, branch `main`, **main file `app/view.py`**.
3. **Advanced settings → Secrets:**
   ```toml
   DATABASE_URL = "postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres"
   ```
4. Deploy.

---

## Problems hit during deploy, and fixes

### A. Build failed on the geo/GEE libraries
`geopandas`, `fiona`, `rasterio`, `earthengine-api` failed to install on the cloud's Python.

**Fix:** the viewer doesn't need them. We split requirements:
- `requirements.txt` — **viewer only** (streamlit, sqlalchemy, psycopg2-binary, pandas,
  plotly, folium, streamlit-folium, shapely, python-dotenv), left unpinned so the cloud's
  Python gets matching wheels.
- `requirements-ingest.txt` — the full stack for the local ingest script.

Confirmed by checking `view.py`'s import chain — no geopandas/fiona/rasterio/ee anywhere.

### B. `sqlalchemy ArgumentError: Expected string or URL object, got None`
`settings.database_url` was `None` — the secret wasn't being read.

**Fixes:**
- Made secret reading robust: direct `st.secrets[key]` in a try/except instead of `key in st.secrets`.
- Confirmed the **`DATABASE_URL` secret was actually saved** in Manage app → Settings → Secrets
  (correct key name, quoted TOML value, no line break inside the URL).

### C. App "blinked" / slow — rerunning on every map interaction
Streamlit reruns the whole script on any interaction, re-querying Supabase each time.

**Fixes:**
- Cached DB reads with `@st.cache_data(ttl=600)` (AOI list, series, geometry).
- `st_folium(..., returned_objects=[])` so pan/zoom no longer triggers a rerun.

---

## Post-deploy security

The database password was shared in plain text during setup, so it should be rotated:
1. Supabase → **Project Settings → Database → Reset database password**.
2. Update the `DATABASE_URL` secret in Streamlit Cloud with the new password → the app reboots.

---

## Files that made deployment work

| File | Role |
|------|------|
| `requirements.txt` | Slim, viewer-only deps (cloud build) |
| `requirements-ingest.txt` | Full deps for local ingest |
| `app/config.py` | Secrets-first, env fallback |
| `.streamlit/secrets.toml.example` | Template for the Secrets box (real file gitignored) |
| `db/init.sql` | Schema run against Supabase |

---

## Redeploying after changes

Just push to `main` — Streamlit Cloud auto-rebuilds. If it doesn't, **Manage app → Reboot**.
Secrets persist across reboots; update them only when the DB URL or password changes.
