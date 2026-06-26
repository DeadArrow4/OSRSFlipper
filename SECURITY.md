# Security Policy

## Secrets

Do not commit:

- OpenAI API keys
- `.env`
- SQLite databases
- logs
- backups
- release packages
- RuneLite account runtime files
- encrypted local API-key records

## Before every push

Run:

```powershell
git status --ignored
git diff --cached --name-only
```

Check that private files are not staged.

## Reporting issues

Do not include API keys, database files, logs with personal account names, or RuneLite JSON files in public issues.
