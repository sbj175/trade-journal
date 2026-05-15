---
id: OPT-56
title: Add onboarding page for Initial Sync
status: Duplicate
priority: Low
assignee: Steve Johnson
created: 2026-02-15
canceled: 2026-02-25
labels: []
related: []
linear_url: https://linear.app/optionedge/issue/OPT-56/add-onboarding-page-for-initial-sync
---

# OPT-56: Add onboarding page for Initial Sync

The "Initial Sync" button currently lives on the Chains page, but it's really a first-run/setup action that doesn't belong there anymore.

Consider adding a dedicated onboarding page that:

* Detects first-time use (no data in DB)
* Guides the user through OAuth credential setup (if not already configured)
* Runs the initial full sync with progress indication
* Redirects to the main app once complete

This would clean up the Chains page and provide a better first-run experience.

## Comments

### 2026-02-17 — Steve Johnson

In the meantime the "Initial Sync" was moved to a tab in the Settings page.
