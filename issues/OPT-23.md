---
id: OPT-23
title: Multi-tenant support
status: Duplicate
priority: High
assignee: Steve Johnson
created: 2026-02-04
canceled: 2026-02-25
labels: [Research]
related: [OPT-51]
linear_url: https://linear.app/optionedge/issue/OPT-23/multi-tenant-support
---

# OPT-23: Multi-tenant support


## Comments

### 2026-02-04 — Steve Johnson

## Multi-Tenant Support Feasibility Assessment

### Executive Summary
Multi-tenant support is **feasible but requires significant refactoring** (estimated 33-44 days). The current architecture is fundamentally single-user with no user isolation in the database.

---

### Current Architecture Issues

**No User Concept:**
- No `users` table exists - app doesn't track application users
- No `user_id` columns in any table
- Data organized by `account_number` (Tastytrade account, not app user)
- Authentication validates against Tastytrade API directly, not an app user database

**Credential Handling:**
- Tastytrade credentials stored in-memory only (by design for security)
- Session stores plaintext password in `SessionData` class (`auth_manager.py:17-21`)
- No persistent credential storage

**Data Isolation Gaps:**
- All queries return all data, filtered application-side
- No database-level user constraints
- Example: `db.get_open_positions()` returns ALL positions, then filters in Python

---

### Required Changes

#### Database Schema (7 tables affected + 3 new)

**New tables needed:**
1. `users` - app user accounts with password hashes
2. `user_accounts` - junction table mapping app users to Tastytrade accounts
3. `audit_log` - compliance/security logging

**Existing tables need `user_id` column:**
- `accounts`, `orders`, `order_chains`, `positions`, `raw_transactions`, `position_lots`, `lot_closings`

#### Authentication Rewrite
- Separate app authentication from Tastytrade authentication
- App login → validate against `users` table
- Tastytrade binding → optional after app login
- Encrypt Tastytrade credentials with user-derived key

#### Endpoint Updates (extensive)
Every API endpoint in `app.py` needs user context:
- `/api/chains` (lines 1018-1120)
- `/api/positions` (lines 1819-1896)
- All sync endpoints (lines 2025-2264)
- Background sync needs per-user management

---

### Effort Estimate

| Component | Effort | Risk |
|-----------|--------|------|
| Database schema migration | 3-4 days | Medium |
| AuthManager rewrite | 5-7 days | High |
| App.py endpoint updates | 8-10 days | Medium |
| Order processor updates | 3-4 days | Low |
| Query method updates | 5-6 days | Medium |
| Tests & validation | 5-7 days | High |
| Frontend updates | 2-3 days | Low |
| Deployment & migration | 2-3 days | Medium |
| **Total** | **33-44 days** | **High** |

---

### Recommendations

**Phased Approach (Recommended):**
1. Phase 1 (2 weeks): Add users table and basic isolation
2. Phase 2 (2 weeks): Implement credential encryption
3. Phase 3 (2 weeks): Full endpoint updates
4. Phase 4 (1 week): Testing and validation
5. Phase 5 (1 week): Data migration and deployment

**Alternative - Container Isolation:**
Instead of code-level multi-tenancy, consider per-user Docker containers with separate databases. Simpler to implement but higher infrastructure cost.

---

### Critical Success Factors
1. **Credential encryption** - use industry standards (Fernet, PBKDF2/Argon2)
2. **Data migration strategy** - test with production-like data
3. **Security testing** - SQL injection, cross-user access, credential leakage
4. **Audit logging** - every data access logged
5. **Backward compatibility** - handle existing single-user deployments

---

### Key Code References
- `src/utils/auth_manager.py:14-25` - SessionData class (credentials in memory)
- `src/database/db_manager.py:49-295` - Database schema (no user_id)
- `app.py:247-263` - require_auth() returns username not user_id
- `app.py:1819-1852` - Example endpoint without user isolation
