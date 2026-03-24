# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

We take the security of Paladino seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do NOT report security issues through public GitHub issues.**

### How to Report

1. **Email**: Send an email to `security@paladino-project.org`
2. **Subject Line**: `[Security] Paladino Vulnerability Report`
3. **Include**:
   - Description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact
   - Any suggested fixes (if applicable)

### What to Expect

- **Initial Response**: We will acknowledge your report within **48 hours**
- **Status Update**: We will provide a status update within **5 business days**
- **Resolution Timeline**: We aim to resolve critical issues within **30 days**

### Process

1. **Triage**: We will review your report and confirm whether it's a valid security issue
2. **Assessment**: We will assess the severity and potential impact
3. **Fix Development**: We will work on a fix (you may be invited to collaborate)
4. **Disclosure**: We will coordinate responsible disclosure with you

### Recognition

We appreciate responsible disclosure and will acknowledge your contribution (unless you prefer to remain anonymous) in our security advisories.

## Security Best Practices for Users

### Required Configuration

1. **Never commit `.env` files** - Always use `.env.example` as a template
2. **Change default credentials** - Neo4j password must be changed from defaults
3. **Use HTTPS in production** - Never expose Neo4j or the API over plain HTTP
4. **Enable Neo4j authentication** - Never run with `auth=none`

### Network Security

- Run Neo4j and the API on a private network when possible
- Use firewall rules to restrict access to necessary ports only
- Consider using a reverse proxy (nginx, Traefik) for production deployments

### Data Protection

- Paladino processes sensitive public spending data - ensure compliance with local regulations
- Implement proper backup and disaster recovery procedures
- Audit access logs regularly

## Known Limitations

- LLM-generated Cypher queries use blocklist-based filtering (not foolproof)
- Local-first architecture means security depends on host machine security
- No built-in user authentication/authorization (single-user by design)

## Security Updates

Security updates will be announced via:
- GitHub Security Advisories
- Release notes with `[SECURITY]` tag
- @security-announcements team (for critical issues)

---

Thank you for helping keep Paladino and its users safe!
