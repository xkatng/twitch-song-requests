# Security Policy

## Credential Safety

**NEVER commit sensitive files to this repository.**

The following files contain secrets and must NEVER be committed:

| File | Contains |
|------|----------|
| `.env` | API keys, client secrets, channel name |
| `.twitch_cache` | Twitch OAuth tokens |
| `.spotify_cache` | Spotify refresh tokens |
| `.tio.tokens.json` | TwitchIO token storage |
| `*.pem` | SSL certificates |
| `*.key` | Private keys |
| `tokens.json` | Any token storage |

## Before Committing

Always verify no secrets are staged:

```bash
git status
git diff --cached
```

## If You Accidentally Commit Secrets

1. **Immediately revoke the exposed credentials:**
   - Spotify: https://developer.spotify.com/dashboard → Your App → Reset Client Secret
   - Twitch: https://dev.twitch.tv/console → Your App → New Secret

2. **Remove from git history** (if not yet pushed):
   ```bash
   git reset HEAD~1
   ```

3. **If already pushed**, the secret is compromised. Revoke and regenerate all affected credentials.

## Reporting Security Issues

If you discover a security vulnerability, please open an issue or contact the maintainer directly.

## For Contributors

- Use `.env.example` as a template - it contains only placeholder values
- Never hardcode credentials in source files
- The `.gitignore` is configured to exclude sensitive files - do not modify it to include them
