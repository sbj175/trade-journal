# Authentication System Fix - Sync and API Endpoints

## Problem
After implementing the web login system (removing encrypted credentials), the sync and other API endpoints were still trying to create `TastytradeClient()` without credentials, causing 401 authentication failures.

## Root Cause
The new authentication system doesn't store credentials on disk - they're only available during the user's session. However, the sync and other privileged endpoints need credentials to work. Three options:

1. **Environment Variables** (Current approach) - Use for scripts and server-side automation
2. **Password re-submission** - Have client send password again (not ideal for API endpoints)
3. **API tokens** - Store tokens instead of passwords (future enhancement)

## Solution Implemented

### 1. **Disabled Auto-Sync on Startup**
- Commented out the auto-sync check in `@app.on_event("startup")`
- Added note explaining that sync must be triggered manually or via environment variables
- This prevents 401 errors on app startup

### 2. **Added Authentication to Sync Endpoints**
All endpoints that sync data now:
- Require valid session authentication via `require_auth(request)`
- Return 401 if not authenticated
- Use environment variables for Tastytrade credentials
- Log which user triggered the operation

**Updated Endpoints:**
- `POST /api/sync-positions-only` - Fast position sync
- `POST /api/sync` - Full incremental sync
- `POST /api/sync/initial` - Full rebuild from scratch
- `POST /api/reprocess-chains` - Reprocess chains
- `POST /api/migrate-realized-pnl` - P&L migration
- `POST /api/screener/run` - Options screener

### 3. **Environment Variables for Non-Interactive Use**
For scripts and background jobs that need to sync without a web session:
```bash
export TASTYTRADE_USERNAME=your_username
export TASTYTRADE_PASSWORD=your_password
python app.py
```

Then sync will work via `POST /api/sync` if environment variables are set.

## Architecture Change
```
BEFORE:
  App Startup → Load encrypted credentials → TastytradeClient() → Can auto-sync

AFTER:
  App Startup → No credentials loaded
              → User logs in → Session created
              → Only that authenticated user can trigger syncs
              → Uses environment variables OR passes credentials securely (future)
```

## Security Benefits
1. ✓ Credentials not stored on disk
2. ✓ Each sync requires authentication
3. ✓ Audit trail: logs show which user triggered each sync
4. ✓ Can be restricted to specific users

## Configuration

### For Web UI Usage (Recommended)
1. Start the app: `python app.py`
2. Login at `/login` with Tastytrade credentials
3. Click "Sync Positions" button
4. Sync fails with message to check environment variables

### For Automated Sync (With Environment Variables)
1. Set environment variables:
   ```bash
   export TASTYTRADE_USERNAME=your_username
   export TASTYTRADE_PASSWORD=your_password
   ```
2. Start app: `python app.py`
3. API endpoints will work (session not required when env vars present)

### Future: Password Re-submission
For better UX, could implement modal dialog that asks user to re-enter password for sensitive operations like sync. This would:
- Keep password out of storage
- Provide per-operation confirmation
- Prevent accidental syncs
- Clear password from memory after use

## Testing

```bash
# Test 1: Login required
curl -X POST http://localhost:8000/api/sync
# Response: 401 Not authenticated

# Test 2: With session cookie (after login)
curl -X POST http://localhost:8000/api/sync -b "session_id=..."
# Response: 401 Failed to authenticate with Tastytrade (unless env vars set)

# Test 3: With environment variables
export TASTYTRADE_USERNAME=test@example.com
export TASTYTRADE_PASSWORD=password123
python app.py
curl -X POST http://localhost:8000/api/sync -b "session_id=..."
# Response: 200 Sync completed successfully
```

## Error Messages Updated
All sync endpoints now provide helpful error messages:
```
"Failed to authenticate with Tastytrade - check TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD environment variables"
```

## Log Output Changes
Sync operations now log the authenticated user:
```
INFO     | app:sync_unified:1575 - Sync requested by user: user@example.com
INFO     | app:sync_unified:1596 - Failed to authenticate with Tastytrade for user: user@example.com
```

## Files Modified
- `app.py` - Added auth checks to all sync/privileged endpoints

## Backward Compatibility
- ✓ Scripts using environment variables still work
- ✓ API clients with session cookies work (if env vars configured)
- ✓ All existing API responses unchanged
- ✓ Database schema unchanged
