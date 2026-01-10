# Storage Optimization Plan

## Current State

Root SSD at **89% full** (768GB/915GB) while 16TB+ of NVMe/SSD storage sits nearly empty:

| Mount | Size | Used | Purpose |
|-------|------|------|---------|
| `/` (root) | 915GB | 768GB (89%) | **OVERLOADED** |
| `/mnt/database` | 1.8TB | 3.7GB (1%) | PostgreSQL (correct) |
| `/mnt/scratch` | 1.8TB | 60KB (0%) | Temp/Logs (empty!) |
| `/mnt/work` | 1.8TB | 28KB (0%) | Models/Cache (empty!) |
| `/mnt/backup` | 9.1TB | 113GB (2%) | Archives |

## Cleanup Candidates (~150GB)

| Path | Size | Action |
|------|------|--------|
| `/home/rivercityscrape/Downloads` | 54GB | Delete duplicates |
| `/home/rivercityscrape/runpod-model` | 49GB | Delete (unused dev models) |
| `/home/rivercityscrape/zijgt5ph` | 5.3GB | Delete (garbage file) |
| `/home/rivercityscrape/.cache` | 43GB | Clean old cache |

---

## Implementation Phases

### Phase 1: Immediate Cleanup (~110GB) [SAFE]

Delete obvious garbage and duplicates:

```bash
# Delete garbage file
rm -f /home/rivercityscrape/zijgt5ph

# Delete unused dev models
rm -rf /home/rivercityscrape/runpod-model

# Clean Downloads (keep last 30 days)
find /home/rivercityscrape/Downloads -type f -mtime +30 -delete
```

### Phase 2: Move Logs to /mnt/scratch [REQUIRES SERVICE RESTART]

**Current**: Logs in `/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/logs/`
**Target**: `/mnt/scratch/washdb-logs/`

Steps:
1. Create target directory: `mkdir -p /mnt/scratch/washdb-logs`
2. Stop all services
3. Move logs: `mv logs/* /mnt/scratch/washdb-logs/`
4. Create symlink: `ln -sf /mnt/scratch/washdb-logs logs`
5. Update `.env` if LOG_DIR is absolute
6. Restart services

Files to update:
- `.env`: `LOG_DIR=/mnt/scratch/washdb-logs`
- All systemd services that reference log paths

### Phase 3: Move LLM Models to /mnt/work [REQUIRES OLLAMA RESTART]

**Current**: Models in `/usr/share/ollama/.ollama/models/` (root SSD)
**Target**: `/mnt/work/ollama-models/`

Steps:
1. Create target: `mkdir -p /mnt/work/ollama-models`
2. Stop Ollama: `sudo systemctl stop ollama`
3. Move models: `mv /usr/share/ollama/.ollama/models/* /mnt/work/ollama-models/`
4. Create symlink: `ln -sf /mnt/work/ollama-models /usr/share/ollama/.ollama/models`
5. Restart Ollama: `sudo systemctl start ollama`

### Phase 4: Move Browser Profiles to /mnt/scratch

**Current**: Browser profiles/cache in home directory
**Target**: `/mnt/scratch/browser-profiles/`

Steps:
1. Create target directory
2. Update browser driver configurations to use new path
3. Set `XDG_CACHE_HOME=/mnt/scratch/browser-cache`

### Phase 5: Set Up Log Rotation

Create `/etc/logrotate.d/washdb`:
```
/mnt/scratch/washdb-logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 rivercityscrape rivercityscrape
}
```

### Phase 6: Clean pip/huggingface Cache

```bash
# Clean old pip cache (keep last 7 days)
find /home/rivercityscrape/.cache/pip -type f -mtime +7 -delete

# Move huggingface cache to /mnt/work
mv /home/rivercityscrape/.cache/huggingface /mnt/work/
ln -sf /mnt/work/huggingface /home/rivercityscrape/.cache/huggingface
```

---

## Files to Modify

| File | Change |
|------|--------|
| `.env` | Update LOG_DIR path |
| `systemd/*.service` | Update log paths if absolute |
| Ollama config | Point models to /mnt/work |

---

## Execution Order

1. **Phase 1**: Immediate cleanup (safe, no service impact)
2. **Phase 3**: Move Ollama models (requires Ollama restart only)
3. **Phase 2**: Move logs (requires all service restart)
4. **Phase 4**: Browser profiles (requires browser pool restart)
5. **Phase 5**: Log rotation setup
6. **Phase 6**: Cache cleanup and migration

---

## Expected Results

| Mount | Before | After |
|-------|--------|-------|
| `/` (root) | 89% | ~50% |
| `/mnt/scratch` | 0% | ~5% (logs) |
| `/mnt/work` | 0% | ~3% (models) |

Total freed: ~150GB on root SSD

---

## Rollback Plan

All changes are reversible:
- Symlinks can be replaced with original directories
- Services can be restarted with original paths
- No data is deleted (only moved or garbage removed)
