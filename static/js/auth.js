/**
 * OptionLedger Auth Client
 *
 * Shared auth module loaded on every page. Handles:
 * - Loading Supabase config from backend
 * - Initializing Supabase JS client
 * - Token management (getAccessToken, getUser)
 * - Auth-aware fetch wrapper (authFetch)
 * - Login redirect (requireAuth)
 * - Sign out
 *
 * When auth is disabled (no SUPABASE_JWT_SECRET on server), all functions
 * are no-ops and authFetch behaves like regular fetch.
 */

window.Auth = (() => {
    let _config = null;       // { auth_enabled, supabase_url, supabase_anon_key }
    let _supabase = null;     // Supabase client instance
    let _initialized = false;
    let _initPromise = null;

    /**
     * Load auth config from backend and initialize Supabase client.
     * Safe to call multiple times — returns cached promise.
     */
    async function init() {
        if (_initPromise) return _initPromise;
        _initPromise = _doInit();
        return _initPromise;
    }

    async function _doInit() {
        try {
            const resp = await fetch('/api/auth/config');
            _config = await resp.json();
        } catch (e) {
            console.warn('Auth config fetch failed, assuming auth disabled:', e);
            _config = { auth_enabled: false, supabase_url: '', supabase_anon_key: '' };
        }

        if (_config.auth_enabled && _config.supabase_url && _config.supabase_anon_key) {
            // Wait for Supabase SDK to be available
            if (typeof window.supabase === 'undefined') {
                console.warn('Supabase SDK not loaded');
                _initialized = true;
                return;
            }
            _supabase = window.supabase.createClient(
                _config.supabase_url,
                _config.supabase_anon_key
            );
        }

        _initialized = true;
    }

    /**
     * Returns true if auth is enabled on the server.
     */
    function isAuthEnabled() {
        return _config?.auth_enabled === true;
    }

    /**
     * Get the current access token (JWT) from the Supabase session.
     * Returns null if auth is disabled or no session exists.
     */
    async function getAccessToken() {
        if (!_config?.auth_enabled || !_supabase) return null;

        const { data: { session } } = await _supabase.auth.getSession();
        return session?.access_token || null;
    }

    /**
     * Get the current user info from the Supabase session.
     * Returns null if no session or auth disabled.
     */
    async function getUser() {
        if (!_config?.auth_enabled || !_supabase) return null;

        const { data: { session } } = await _supabase.auth.getSession();
        return session?.user || null;
    }

    /**
     * Sign out and redirect to /login.
     */
    async function signOut() {
        if (_supabase) {
            await _supabase.auth.signOut();
        }
        window.location.href = '/login';
    }

    /**
     * Redirect to /login if auth is enabled and no valid session exists.
     * Call this in each page's init() method.
     */
    async function requireAuth() {
        await init();
        if (!_config?.auth_enabled) return; // Auth disabled, allow access

        const token = await getAccessToken();
        if (!token) {
            window.location.href = '/login';
            // Return a never-resolving promise to halt the caller's init chain
            return new Promise(() => {});
        }
    }

    /**
     * Auth-aware fetch wrapper. Attaches Authorization header when auth is enabled.
     * Drop-in replacement for fetch().
     */
    async function authFetch(url, options = {}) {
        if (_config?.auth_enabled) {
            const token = await getAccessToken();
            if (token) {
                options.headers = options.headers || {};
                if (options.headers instanceof Headers) {
                    options.headers.set('Authorization', `Bearer ${token}`);
                } else {
                    options.headers['Authorization'] = `Bearer ${token}`;
                }
            } else {
                // No token but auth is enabled — redirect to login
                window.location.href = '/login';
                // Return a never-resolving promise to prevent further execution
                return new Promise(() => {});
            }
        }

        const response = await fetch(url, options);

        // Beta capacity gate: redirect new users who hit the backend safety net
        if (response.status === 403) {
            try {
                const cloned = response.clone();
                const body = await cloned.json();
                if (body.detail === 'beta_full') {
                    window.location.href = '/beta-full';
                    return new Promise(() => {});
                }
            } catch (e) { /* not JSON or parse error — fall through */ }
        }

        return response;
    }

    /**
     * Redirect to Settings if auth is enabled and user has no Tastytrade
     * credentials configured. Call after requireAuth() on data pages.
     */
    async function requireTastytrade() {
        if (!_config?.auth_enabled) return; // Single-user mode uses .env
        try {
            const resp = await authFetch('/api/settings/credentials');
            if (resp.ok) {
                const data = await resp.json();
                if (!data.configured) {
                    window.location.href = '/settings?tab=connection&onboarding=1';
                    return new Promise(() => {}); // Halt caller's init chain
                }
            }
        } catch (e) { /* Let page load, fail gracefully elsewhere */ }
    }

    /**
     * Build a WebSocket URL with token for authenticated connections.
     */
    async function getAuthenticatedWsUrl(path) {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        let wsUrl = `${protocol}//${location.host}${path}`;

        if (_config?.auth_enabled) {
            const token = await getAccessToken();
            if (token) {
                wsUrl += `?token=${encodeURIComponent(token)}`;
            }
        }

        return wsUrl;
    }

    return {
        init,
        isAuthEnabled,
        getAccessToken,
        getUser,
        signOut,
        requireAuth,
        requireTastytrade,
        authFetch,
        getAuthenticatedWsUrl,
    };
})();
