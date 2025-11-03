# Authentication System Implementation

## Overview

The Trade Journal application has been migrated from an encrypted credential storage system to a web-based login prompt with session-based authentication. This provides better security and a cleaner user experience.

## Key Changes

### 1. New Authentication System

#### Files Created
- **`static/login.html`**: Login page with form UI (Tailwind-styled)
- **`src/utils/auth_manager.py`**: Session management and authentication logic

#### Removed Files
- **`setup_credentials.py`**: No longer needed (credentials not stored)
- **`encrypted_credentials.py`**: No longer needed (credentials not stored)
- **`crypto.key`**: No longer needed (credentials not stored)
- **`src/utils/credential_manager.py`**: No longer needed (credentials not stored)

### 2. Backend Changes

#### app.py
- Added import: `from src.utils.auth_manager import AuthManager`
- Added initialization: `auth_manager = AuthManager()`
- Added Pydantic model: `LoginRequest`
- Added authentication endpoints:
  - `GET /login` - Serves login page
  - `POST /api/auth/login` - Authenticates user and creates session
  - `POST /api/auth/logout` - Invalidates session
  - `GET /api/auth/verify` - Checks if session is valid
- Added helper function: `require_auth(request)` - Validates session for protected endpoints
- Updated protected endpoints to require authentication:
  - `GET /` (Open Positions)
  - `GET /chains` (Order Chains)

#### src/api/tastytrade_client.py
- Modified constructor to accept optional `username` and `password` parameters
- Credentials now loaded from parameters (for session) or environment variables (for scripts)
- Removed dependency on `CredentialManager`

#### src/sync_trades.py
- Updated to use environment variables instead of encrypted credentials
- No longer depends on `CredentialManager`

### 3. Frontend Changes

#### static/login.html
- New login page with form
- Email/password input fields
- Error message display
- Loading state indicator
- Submits to `/api/auth/login` endpoint

#### static/positions.html
- Added auth check in `init()` function
- Redirects to login page if not authenticated
- Added `username` to state
- Added logout button in navbar
- Added `logout()` method to handle logout

#### static/chains-v2.html
- Added logout button in navbar
- Displays username in header

#### static/js/app-v2.js
- Added `username` to state
- Added auth check in `init()` function
- Redirects to login page if not authenticated
- Added `logout()` method to handle logout

## How It Works

### Login Flow
1. User visits `http://localhost:8000/`
2. Root page redirects to `/login` (not authenticated)
3. User enters credentials and submits login form
4. Form posts to `/api/auth/login` with username/password
5. Backend authenticates against Tastytrade API
6. On success:
   - Session ID is generated (random token)
   - Session is stored in AuthManager (in-memory)
   - Session cookie is set (HTTP-only, 1 hour expiration)
   - User is redirected to main page
7. Frontend verifies session with `/api/auth/verify` on page load
8. All API calls are made with valid session cookie

### Logout Flow
1. User clicks logout button
2. Frontend calls `POST /api/auth/logout`
3. Backend removes session from AuthManager
4. Response clears session cookie
5. User is redirected to `/login`

### Session Management
- Sessions stored in-memory in `AuthManager.sessions` dictionary
- Session ID is random 32-character URL-safe token
- Each session tracks username and creation timestamp
- Sessions expire after 1 hour of inactivity
- Expired sessions are cleaned up on validation

## Security Considerations

### What Changed
- **Before**: Credentials encrypted on disk with Fernet cipher, loaded at startup
- **After**: Credentials never stored on disk, validated at login, only held in memory for session

### Security Benefits
1. **No persistent credential storage** - Credentials never written to disk
2. **Session-based auth** - Each request is authenticated independently
3. **HTTP-only cookies** - Session tokens can't be accessed via JavaScript
4. **SameSite cookies** - CSRF protection
5. **Per-session validation** - Credentials validated fresh each time

### Production Recommendations
1. Set `secure=True` on cookies (HTTPS only)
2. Use HTTPS in production
3. Set appropriate CORS policy
4. Consider adding rate limiting to login endpoint
5. Add logging for failed authentication attempts
6. Consider setting shorter session timeout for sensitive operations

## API Endpoints

### Authentication Endpoints

```
POST /api/auth/login
Content-Type: application/json
Body: { "username": "...", "password": "..." }
Response: 200 { "message": "Login successful" }
          401 { "detail": "Invalid username or password" }
```

```
POST /api/auth/logout
Response: 200 { "message": "Logged out successfully" }
```

```
GET /api/auth/verify
Response: 200 { "authenticated": true, "username": "..." }
          401 { "detail": "Not authenticated" }
```

## Environment Variables

The application still supports environment variables for credential-based scripts:
- `TASTYTRADE_USERNAME` - For scripts like `sync_trades.py`
- `TASTYTRADE_PASSWORD` - For scripts like `sync_trades.py`

## Migration Notes

- Old credential files have been deleted
- No migration script needed (credentials not persisted)
- Users must log in through web UI (no automatic login)
- API scripts must use environment variables instead of encrypted credentials

## Testing the Implementation

1. Start the app: `python app.py`
2. Visit `http://localhost:8000/`
3. Should redirect to `/login`
4. Enter Tastytrade credentials
5. Should authenticate and redirect to positions page
6. Click logout button
7. Should redirect to `/login`

## Troubleshooting

### "Not authenticated" error on protected pages
- Session may have expired (1 hour timeout)
- Try logging out and back in
- Check browser developer tools for session cookie

### "Invalid username or password"
- Verify credentials are correct
- Check that Tastytrade API is reachable
- See console logs for detailed error messages

### Session cookie not being set
- Check browser cookie settings
- Make sure cookies are enabled for localhost
- Verify response includes Set-Cookie header
