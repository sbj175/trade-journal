---
id: OPT-55
title: Stream progress updates during Initial Sync
status: Backlog
priority: Low
assignee: Steve Johnson
created: 2026-02-14
labels: []
related: [OPT-54]
linear_url: https://linear.app/optionedge/issue/OPT-55/stream-progress-updates-during-initial-sync
---

# OPT-55: Stream progress updates during Initial Sync

## Summary

The Initial Sync operation takes several seconds and currently provides no feedback beyond a spinner overlay. Add real-time progress updates so the user can see what's happening.

## Current Behavior

* User clicks Initial Sync → confirmation dialog → spinner overlay with static "Rebuilding database..." message
* No visibility into which step is running or how far along it is
* The operation involves multiple distinct phases that could each report progress

## Proposed Approach

Use **Server-Sent Events (SSE)** to stream progress from the backend to the frontend during Initial Sync. SSE is simpler than WebSocket for this use case (one-directional, server-to-client).

### Progress phases to report:

1. "Fetching transactions..." → "Fetched 750 transactions from 3 accounts"
2. "Processing orders..." → "Created 268 orders"
3. "Building chains..." → "Built 127 chains"
4. "Detecting strategies..." → "Detected strategies for 127 chains"
5. "Updating cache..." → "Cache updated"
6. "Fetching positions..." → "Updated 83 positions"
7. "Complete"

### Implementation

**Backend (**`app.py`):

* New endpoint `POST /api/sync/initial/stream` returning `text/event-stream`
* Each phase sends an SSE event with `{ phase, message, progress_pct }`
* Use `StreamingResponse` from FastAPI

**Frontend (**`chains-dense.html` / `app.js`):

* Replace `fetch()` with `EventSource` or `fetch()` with `ReadableStream`
* Update overlay text dynamically as events arrive
* Show progress bar or step indicator

### Alternative: Chunked date ranges

For very large accounts, could also chunk the transaction fetch by month (e.g., 12 requests of \~1 month each) and report progress per chunk. The Tastytrade SDK already handles pagination internally (`per_page=250`), so the main benefit would be showing incremental progress rather than performance.

## Priority

Low — the spinner overlay added in [OPT-54](https://linear.app/optionedge/issue/OPT-54/chain-as-source-of-truth-unify-positions-and-chains-architecture) is an acceptable interim solution. This is a UX polish item.
