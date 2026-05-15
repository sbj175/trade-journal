---
id: OPT-47
title: Upgrade the python SDK to re-enable authentication
status: Done
priority: Urgent
assignee: Steve Johnson
created: 2026-02-11
started: 2026-02-11
completed: 2026-02-11
labels: [Bug]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-47/upgrade-the-python-sdk-to-re-enable-authentication
---

# OPT-47: Upgrade the python SDK to re-enable authentication

### Step 1: Get your OAuth Credentials

Before you upgrade your code, you need to get your new keys from the Tastytrade website:

1. Log in to [my.tastytrade.com](<https://my.tastytrade.com>).
2. Go to **Manage > My Profile > API**.
3. Click **OAuth Applications** and then **+ New OAuth client**.
4. Give it a name, set the redirect URI to `http://localhost:8000` (it just needs a placeholder), and select all scopes (**read, trade, openid**).
5. **Crucial:** Save your **Client ID** and **Client Secret** immediately.
6. Click **Manage** next to your new app and select **Create Grant** to get your **Refresh Token**. This token lasts forever.

---

### Step 2: Upgrade and Fix the Code

Run the upgrade in your PyCharm terminal:

Bash

```
pip install --upgrade tastytrade
```

Then, update your script. The old way of logging in will no longer work. Here is the new v12 structure:

Python

```
from tastytrade import Session, Account

# REPLACE THESE with the keys you generated in Step 1
# Note: You no longer use your password in the code!
session = Session(
    client_id='YOUR_CLIENT_ID',
    client_secret='YOUR_CLIENT_SECRET',
    refresh_token='YOUR_REFRESH_TOKEN'
)

# Important: v12 is heavily focused on 'async' but provides sync wrappers
# To get accounts in a standard script:
accounts = Account.get_accounts(session)
print(accounts)
```

### Is it transient?

No. While Tastytrade occasionally has maintenance after hours, the timing with the **v12.0.2 release yesterday** and the official deprecation notices for "Sessions" suggests this is a permanent change. If you don't switch to OAuth2, your bot will likely stay locked out.
