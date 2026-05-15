---
id: OPT-29
title: Implement Notes
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-04
completed: 2026-02-27
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-29/implement-notes
---

# OPT-29: Implement Notes

Implement tags and share them between Positions and Chains

See if this is feasible. For example, I enter a comment on an open position on the Positions page and later go to the chain (open or closed) later on and see that comment.

Maybe tags could work similarly.

## Comments

### 2026-02-04 — Steve Johnson

## Comment Sharing Feasibility Assessment

### Executive Summary
Sharing comments between Positions and Chains pages is **highly feasible**. The infrastructure already exists (chain_id linking, similar localStorage patterns). Recommended approach: database-backed comments (6-8 hours).

---

### Current Implementation

**Positions Page** (`positions-dense.html:775-789`):
- Comments stored in localStorage under key `positionComments`
- Key generation already uses `chain_${chainId}` when available
- Falls back to `pos_${symbol}_${expiration}_${account}` for unenriched positions

**Chains Page** (`chains-dense.html:484-522`):
- Edit modal exists with comment/tag fields
- **Not functional** - save is disabled (line 1353-1354):
  ```javascript
  alert('Trade editing is temporarily disabled...');
  ```

**Key Finding:** Positions already use chain_id for comment keys when available, providing a natural link to chains.

---

### Implementation Options

| Approach | Effort | Persistence | Shareable |
|----------|--------|-------------|-----------|
| Shared localStorage | 2-3h | No (browser only) | Limited |
| **Database-backed** | **6-8h** | **Yes** | **Full** |
| Hybrid (DB + cache) | 12-16h | Yes | Full |

---

### Recommended: Database-Backed Comments

**1. New Database Table:**
```sql
CREATE TABLE chain_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id TEXT NOT NULL UNIQUE,
    account_number TEXT NOT NULL,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chain_id) REFERENCES order_chains(chain_id)
);
```

**2. Backend API Endpoints** (add to `app.py`):
- `GET /api/comments/chain/{chain_id}` - retrieve comment
- `POST /api/comments/chain/{chain_id}` - create/update comment
- `DELETE /api/comments/chain/{chain_id}` - remove comment

**3. Frontend Changes:**
- Replace localStorage calls with fetch() API calls
- Add debouncing to minimize API requests
- Both pages read/write via same endpoints

---

### Technical Considerations

**Unenriched Positions:**
- Positions without chain_id can't link to chains
- Solution: Use `account + underlying + opening_date` as fallback key
- Or ensure all positions get chain_id during sync

**Multiple Legs Per Chain:**
- Iron Condors have 4+ legs grouped together
- Store comments at chain level, not individual leg
- All positions in a chain share the same comment

**Account Filtering:**
- Already synced across pages via localStorage (`trade_journal_selected_account`)
- Comments naturally scope to selected account

---

### Tags Implementation

**Current State:** Not implemented anywhere (modal fields exist but don't save)

**For Shared Tags:**
- Parallel implementation to comments
- New `chain_tags` table with similar structure
- Additional 4-6 hours effort
- Recommend implementing alongside comments

---

### Files to Modify

| File | Changes |
|------|---------|
| `app.py` | Add 3 comment API endpoints |
| `src/database/db_manager.py` | Add table creation in `initialize_database()` |
| `static/positions-dense.html` | Replace localStorage with API calls (lines 771-789) |
| `static/chains-dense.html` | Implement comment save (line 1353-1354) |

---

### Risk Assessment

**Low Risk:**
- No existing functionality to break (chains page comments disabled)
- Simple schema (single new table)
- Chain_id linking already in place

**Medium Risk:**
- Unenriched positions lack chain linking
- API latency could impact UX (mitigate with debouncing)

---

### Recommendation

**Phase 1 - Database Comments (6-8 hours):**
1. Create `chain_comments` table
2. Add backend API endpoints
3. Update Positions page to use API
4. Enable Chains page comment saving
5. Add debouncing for performance

**Phase 2 - Tags (4-6 hours, optional):**
1. Create `chain_tags` table
2. Add tag API endpoints
3. Implement tag UI on both pages

**Total: 10-14 hours for full implementation with tags**
