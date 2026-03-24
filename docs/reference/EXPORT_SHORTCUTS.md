# 🛡️ Paladino CLI Export Shortcuts

## Quick Reference

### In the Investigator REPL (`paladino investigate`)

| Shortcut | Description | Example |
|----------|-------------|---------|
| `.export` | Export last results to JSON | `.export` |
| `.export csv` | Export last results to CSV | `.export csv` |
| `.export json mydata` | Export with custom filename | `.export json mydata` |
| `.save` | Save complete session | `.save` |
| `.save mysession` | Save session with custom name | `.save investigation_001` |
| `.report` | Generate Markdown report | `.report` |
| `.report final` | Generate report with custom name | `.report final_analysis` |
| `help` | Show all commands | `help` |

## Usage Examples

### Example 1: Export Company Data to CSV
```bash
paladino investigate

PALADINO 🔍 > Show me top 10 companies by tenders won
[Results displayed]

PALADINO 🔍 > .export csv
✓ Exported to /path/to/exports/export_20260220_143022.csv
```

### Example 2: Save Complete Investigation Session
```bash
paladino investigate

PALADINO 🔍 > Show PNRR projects
[Results]

PALADINO 🔍 > Show companies with high risk
[Results]

PALADINO 🔍 > .save pnrr_investigation
✓ Session saved to /path/to/exports/session_pnrr_investigation.json
```

### Example 3: Generate Full Report
```bash
paladino investigate

PALADINO 🔍 > [multiple queries...]

PALADINO 🔍 > .report
✓ Report generated: /path/to/reports/report_20260220_143022.md
📄 Open with: code reports/report_20260220_143022.md
```

## Output Locations

- **Exports**: `./exports/` directory
  - `export_YYYYMMDD_HHMMSS.json` or `.csv`
  - `session_YYYYMMDD_HHMMSS.json`

- **Reports**: `./reports/` directory
  - `report_YYYYMMDD_HHMMSS.md`

## File Formats

### JSON Export
```json
[
  {
    "c.nome_normalizzato": "IMPRESA INESISTENTE",
    "count(t)": 168
  },
  ...
]
```

### CSV Export
```csv
c.nome_normalizzato,count(t)
IMPRESA INESISTENTE,168
VIATRIS ITALIA,60
...
```

### Markdown Report
```markdown
# 🛡️ Paladino Investigation Report

**Generated:** 2026-02-20 14:30:22
**Total Queries:** 3

---

## Query 1

```
Show me top 10 companies by tenders won
```

**Results:** 10 rows

| c.nome_normalizzato | count(t) |
|---------------------|----------|
| IMPRESA INESISTENTE | 168      |
| VIATRIS ITALIA      | 60       |
...
```

## Tips

- Use **CSV** for Excel/Google Sheets analysis
- Use **JSON** for programmatic processing
- Use **Reports** for sharing findings with others
- Session files contain ALL queries and results for that session
- Reports are formatted in Markdown (open in VS Code, Obsidian, etc.)

## Keyboard Shortcuts

While in the REPL:
- `Ctrl+C` - Emergency exit
- `Ctrl+D` - Exit (EOF)
- Arrow keys - Navigate history (if supported by terminal)
