# 🔄 Security Migration Guide

**For:** Existing users and developers upgrading to the security-hardened version  
**Date:** February 25, 2026  
**Version:** 0.2.0-security-hardened

---

## ⚠️ Breaking Changes

This release includes **breaking changes** to improve security. Follow this guide to migrate.

### What's Changing

| Change | Impact | Action Required |
|--------|--------|-----------------|
| API Authentication | All API calls now require API key | Generate and configure API keys |
| CORS Configuration | Wildcard (*) no longer allowed | Update allowed origins |
| Neo4j Credentials | No more default passwords | Set secure password in .env |
| Rate Limiting | Requests limited per minute | May need to adjust client code |

---

## Migration Steps

### Step 1: Backup Current Configuration

```bash
# Backup your current .env if it exists
cp .env .env.backup.$(date +%Y%m%d)

# Backup docker-compose.yml if customized
cp infra/docker-compose.yml infra/docker-compose.yml.backup
```

### Step 2: Update Environment Variables

```bash
# Copy new environment template
cp .env.example .env

# Generate secure Neo4j password (REQUIRED)
NEO4J_PASSWORD=$(openssl rand -base64 32)
echo "NEO4J_AUTH=neo4j/$NEO4J_PASSWORD" >> .env
echo "NEO4J_PASSWORD=$NEO4J_PASSWORD" >> .env

# Generate API key (REQUIRED for production)
API_KEY="sk_live_$(openssl rand -hex 16)"
echo "PALADINO_API_KEYS=$API_KEY" >> .env

# Configure allowed origins (REQUIRED)
echo "ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000" >> .env
```

### Step 3: Update Docker Compose

```bash
# Stop current services
docker-compose down

# Remove old Neo4j data (⚠️ WARNING: This deletes existing data!)
# Skip this if you want to keep existing data
docker volume rm paladino_neo4j_data

# Start with new configuration
docker-compose --profile production up -d
```

### Step 4: Update API Clients

**Before (v0.1.0):**
```python
import requests

# No authentication required
response = requests.get("http://localhost:8000/companies/12345678901")
data = response.json()
```

**After (v0.2.0):**
```python
import requests

# API key authentication required
headers = {
    "Authorization": "Bearer sk_live_abc123",  # Your API key
    "X-Request-ID": "unique-request-id"  # Optional, for tracing
}
response = requests.get(
    "http://localhost:8000/companies/12345678901",
    headers=headers
)

if response.status_code == 401:
    print("Authentication failed - check API key")
elif response.status_code == 429:
    print("Rate limited - slow down requests")
else:
    data = response.json()
```

### Step 5: Update Rate Limiting

**Unauthenticated limits:** 20 requests/minute  
**Authenticated limits:** 100 requests/minute

**Example: Add retry logic for rate limiting:**

```python
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session_with_retry():
    session = requests.Session()
    
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429],  # Retry on rate limit
        allowed_methods=["GET", "POST"],
    )
    
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# Usage
session = create_session_with_retry()
response = session.get(
    "http://localhost:8000/query",
    headers={"Authorization": "Bearer sk_live_abc123"}
)
```

---

## Troubleshooting

### Error: "API key required" (401)

**Cause:** Missing or invalid API key

**Solution:**
```bash
# Check your API key is set
echo $PALADINO_API_KEYS

# Verify API key in request
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:8000/health
```

### Error: "Rate limit exceeded" (429)

**Cause:** Too many requests

**Solution:**
1. Wait for the `Retry-After` seconds specified in response header
2. Add retry logic with exponential backoff
3. Use authenticated requests for higher limits

```python
import time

def retry_with_backoff(func, max_retries=3):
    for attempt in range(max_retries):
        response = func()
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            print(f"Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
        else:
            return response
    raise Exception("Max retries exceeded")
```

### Error: "CORS policy" (Browser)

**Cause:** Origin not in allowed list

**Solution:**
```bash
# Add your frontend origin to allowed origins
echo "ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.com" >> .env

# Restart services
docker-compose restart
```

### Error: "Service unavailable" (503)

**Cause:** Neo4j connection failed (possibly wrong credentials)

**Solution:**
```bash
# Check Neo4j credentials
docker-compose logs neo4j | grep -i error

# Verify password is set
grep NEO4J_PASSWORD .env

# Reset Neo4j password if needed
docker-compose down
docker volume rm paladino_neo4j_data
docker-compose up -d
```

### Error: "Query execution failed"

**Cause:** Query timeout or validation failure

**Solution:**
1. Check query complexity - add filters or reduce result size
2. Verify query doesn't use blocked operations (DELETE, DROP, etc.)
3. Check Neo4j performance

```python
# Add limit to queries
query = """
MATCH (c:Company)
RETURN c
LIMIT 100  # Add explicit limit
"""
```

---

## Development Mode

For local development, you can use relaxed settings:

```bash
# .env for development
NEO4J_AUTH=neo4j/dev_password_123
NEO4J_PASSWORD=dev_password_123
PALADINO_API_KEYS=dev_key_123
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000,http://localhost:5173
PALADINO_ENABLE_AUDIT_LOGGING=false
```

⚠️ **WARNING:** Never use these settings in production!

---

## Production Checklist

Before deploying to production:

- [ ] Generated secure Neo4j password (20+ characters)
- [ ] Generated unique API keys (not using examples)
- [ ] Configured specific allowed origins (no wildcards)
- [ ] Enabled audit logging
- [ ] Configured HTTPS/TLS
- [ ] Set up monitoring and alerting
- [ ] Tested backup and restore procedures
- [ ] Reviewed security headers
- [ ] Tested rate limiting under load
- [ ] Documented incident response procedures

---

## Security Best Practices

### API Key Management

1. **Never commit API keys to version control**
   ```bash
   # Add to .gitignore
   .env
   *.key
   secrets/
   ```

2. **Rotate API keys regularly**
   ```bash
   # Generate new key
   NEW_KEY="sk_live_$(openssl rand -hex 16)"
   
   # Update .env
   echo "PALADINO_API_KEYS=$NEW_KEY" >> .env
   
   # Restart services
   docker-compose restart
   ```

3. **Use different keys for different clients**
   ```bash
   # Multiple keys (comma-separated)
   PALADINO_API_KEYS="sk_live_client1,sk_live_client2,sk_live_client3"
   ```

### Password Requirements

- Minimum 20 characters
- Mix of uppercase, lowercase, numbers, symbols
- Not based on dictionary words
- Unique (not reused from other systems)

**Generate secure password:**
```bash
# Option 1: Base64 (32 chars)
openssl rand -base64 32

# Option 2: Hex (32 chars)
openssl rand -hex 16

# Option 3: ASCII (32 chars)
openssl rand -ascii 32
```

---

## Support

### Documentation

- Security Overview: `SECURITY_FIXES_SUMMARY.md`
- Production Checklist: `docs/PRODUCTION_READINESS_CHECKLIST.md`
- API Documentation: `/api/v1/docs` (Swagger UI)

### Getting Help

If you encounter issues during migration:

1. Check logs: `docker-compose logs -f`
2. Review error messages in API responses
3. Check security audit logs: `audit_logs/`
4. Open an issue on GitHub

---

## Rollback Procedure

If you need to rollback to v0.1.0:

```bash
# 1. Stop current services
docker-compose down

# 2. Restore old configuration
git checkout HEAD~1 -- infra/docker-compose.yml
git checkout HEAD~1 -- .env.example

# 3. Restore old .env
cp .env.backup.YYYYMMDD .env

# 4. Restart with old version
docker-compose up -d
```

⚠️ **WARNING:** Rollback will re-introduce security vulnerabilities. Only use for emergency situations.

---

## Changelog

### v0.2.0-security-hardened (2026-02-25)

**Security:**
- ✅ Added API key authentication
- ✅ Fixed CORS configuration
- ✅ Added rate limiting
- ✅ Prevented Cypher injection
- ✅ Fixed credential leakage
- ✅ Added security headers
- ✅ Added query audit logging

**Breaking Changes:**
- API authentication now required
- CORS wildcard no longer allowed
- Default credentials removed

### v0.1.0 (Previous)

- Initial release
- No authentication
- Development-focused configuration

---

**Last Updated:** February 25, 2026  
**Maintained By:** Paladino Security Team
