# Deploying `report_clean_v4.py` to Streamlit

This project has been adjusted so configuration and secrets are not hard-coded. Follow the instructions below to deploy safely to Streamlit Cloud or run locally.

## Files added
- `.streamlit/secrets.toml.example` — example secrets file. Copy to `.streamlit/secrets.toml` locally (do NOT commit real secrets).
- `config/config.json.example` — optional local fallback config file.
- `report_clean_v4.py` — updated to load configuration from Streamlit secrets, environment variables, or `config/config.json`.

## Recommended (Streamlit Cloud)
1. Push your repo to GitHub.
2. Create a new app in Streamlit Cloud and connect your GitHub repo.
3. In the Streamlit app settings, open "Secrets" and paste keys from `.streamlit/secrets.toml.example` (use the same keys and values).
4. Deploy. Streamlit will make the secrets available via `st.secrets`.

## Local run (development)
Option A (recommended):
- Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in real credentials.
- Run: `streamlit run report_clean_v4.py`

Option B: Use environment variables
- Export the required environment variables (DB_HOST, DB_PASSWORD, AWS_ACCESS_KEY_ID, etc.). The script will read from the environment if `st.secrets` is not present.

Option C: Use `config/config.json`
- Create `config/config.json` based on `config/config.json.example` and the script will read values from it when `st.secrets` and environment variables are absent.

## Security notes
- Never commit real secrets to Git. Use `.gitignore` to exclude `.streamlit/secrets.toml` and any local `config/config.json`.
- On Streamlit Cloud, use the Secrets manager UI.

## Troubleshooting
- If you see the warning about missing credentials at app startup, ensure you have set at least `DB_HOST` and `DB_PASSWORD` in secrets, environment, or config file.
- For AWS permissions, ensure the IAM user/role has S3 and Bedrock access if you plan to call Bedrock.

