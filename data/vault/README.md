# User vault

This directory holds your personal data used to fill government forms.
It is **gitignored** — real values must never be committed.

## First-time setup

1. Copy the template:

   ```
   copy user_vault.example.json user_vault.json
   ```

2. Fill in your real details in `user_vault.json`, **or** POST them to
   `POST /api/vault` with a JSON body (partial updates are fine):

   ```
   curl -X POST http://localhost:8000/api/vault ^
        -H "Content-Type: application/json" ^
        -d "{\"full_name\": \"Your Name\", \"state\": \"Kerala\"}"
   ```

3. Check what is populated without ever reading values back:

   ```
   curl http://localhost:8000/api/vault
   ```

## Encryption

Set `VAULT_ENCRYPTION_KEY` in `.env` before populating real data so the
file is encrypted at rest (Fernet + salted scrypt). Without it the file
is plaintext JSON — dev/test only.

## Fields

The schema mirrors `app/vault/resolver.py::UserVault` (all string fields,
blank = not provided). The agent only ever sends semantic references
(e.g. `USER.full_name`) to the LLM; actual values are resolved locally
at execution time and never leave this machine except into the browser.
