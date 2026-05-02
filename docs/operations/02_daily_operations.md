# Daily Operations Playbook

## Purpose

Standard daily workflow for operating the Hermes trading system.

---

## Morning Checklist

Run these checks before the trading session begins:

| # | Check | How | Pass Criteria |
|---|-------|-----|---------------|
| 1 | Alpaca connection | Dashboard: health indicator green | "Alpaca connection healthy" in logs |
| 2 | Universe configuration | Dashboard sidebar: symbol count | Correct symbols for deployment |
| 3 | Scaling profile | Dashboard sidebar: Scaling Profile section | Profile matches deployment size |
| 4 | Scheduler status | Dashboard sidebar: scheduler section | Running if scheduled mode, stopped if manual |
| 5 | Streaming health | Dashboard sidebar: Data Mode section | All buffers FRESH (if streaming active) |
| 6 | Overnight Hermes runs | Dashboard sidebar: Activity log | Review any overnight proposals/alerts |
| 7 | Risk config integrity | `python -c "import hashlib; ..."` | Checksum matches |

### Quick Health Check

```bash
# Check DB stats
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
runs = conn.execute('SELECT COUNT(*) FROM engine_runs WHERE finished_at IS NOT NULL').fetchone()[0]
fills = conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0]
vetoes = conn.execute('SELECT COUNT(*) FROM vetoes').fetchone()[0]
hermes = conn.execute('SELECT COUNT(*) FROM hermes_runs').fetchone()[0]
print(f'Engine runs: {runs}, Fills: {fills}, Vetoes: {vetoes}, Hermes runs: {hermes}')
conn.close()
"
```

---

## During-Session Monitoring

### Dashboard Indicators

| Indicator | Location | Healthy | Investigate |
|-----------|----------|---------|-------------|
| Status dot | Top of main page | `O` (green) | `!` (red) |
| Heartbeat | `logs/engine.log` | Every 30s | Missing > 2 min |
| Hermes last run | Sidebar | Recent (< 24h) | Stale or missing |
| Stream health | Sidebar Data Mode | All FRESH | STALE or DEAD |
| Health notifications | Main page banners | None | Any CRITICAL |

### Log Monitoring

```bash
# Watch for errors in real-time
Get-Content logs\engine.log -Wait | Select-String "ERROR|CRITICAL"

# Check recent fills
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
rows = conn.execute('SELECT symbol, side, fill_price, timestamp FROM fills ORDER BY fill_id DESC LIMIT 5').fetchall()
for r in rows: print(f'{r[3]}: {r[0]} {r[1]} @ {r[2]}')
conn.close()
"
```

### Alert Review

Check for new alerts in the dashboard sidebar:
- **Pending proposals:** Review and accept/decline as needed
- **Hermes alerts:** Review low-confidence warnings
- **Health events:** Check for degraded components

---

## End-of-Day Review

### Analytics Review

1. Open Analytics page in dashboard (`2_Analytics`)
2. Review Session tab: bars processed, fills, vetoes
3. Review Strategy tab: PnL, win rate, drawdown
4. Review Risk tab: utilization, veto rate
5. Review Hermes tab: directive distribution, confidence

### Export Reports

Use the CSV export buttons on the Analytics page to save daily reports.

### Hermes Decision Quality

1. Review today's Hermes runs in sidebar activity log
2. Check per-symbol decisions for accuracy
3. Note any patterns in low-confidence alerts
4. Review correlation warnings

### Risk Check

```python
# Quick risk summary
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
vetoes = conn.execute('SELECT COUNT(*) FROM vetoes WHERE timestamp >= date("now")').fetchone()[0]
fills = conn.execute('SELECT COUNT(*) FROM fills WHERE timestamp >= date("now")').fetchone()[0]
print(f"Today: {fills} fills, {vetoes} vetoes (veto rate: {vetoes/(fills+vetoes)*100:.1f}%)" if (fills+vetoes) > 0 else "No activity today")
conn.close()
```

### Pre-Close Checklist

| # | Check | Action |
|---|-------|--------|
| 1 | Open positions | Verify with broker, not just engine |
| 2 | Pending orders | Cancel any GTC orders if desired |
| 3 | Hermes proposals | Accept/decline pending proposals |
| 4 | Scheduler | Stop if not needed overnight |
| 5 | Streaming | Stop if not needed overnight |

---

## Weekly Review

Every Friday (or end of trading week):

1. Review weekly analytics export
2. Check Hermes accuracy over the week
3. Review scaling profile adequacy
4. Archive old Hermes runs if needed:
   - Dashboard → State Management → Archive & Reset
5. Update `docs/operations/VERSION.md` if any config changes were made
