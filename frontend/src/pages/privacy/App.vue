<script setup>
const navLinks = [
  { href: '/positions', label: 'Positions' },
  { href: '/ledger', label: 'Ledger' },
  { href: '/reports', label: 'Reports' },
  { href: '/risk', label: 'Risk' },
]
</script>

<template>
  <!-- Navigation -->
  <nav class="bg-tv-panel border-b border-tv-border sticky top-0 z-50">
    <div class="flex items-center justify-between h-16 px-4">
      <div class="flex items-center gap-8">
        <span class="text-tv-blue font-semibold text-2xl">
          <i class="fas fa-chart-line mr-2"></i>OptionLedger
        </span>
        <div class="flex items-center border-l border-tv-border pl-8 gap-4">
          <a v-for="link in navLinks" :key="link.href" :href="link.href"
             class="text-tv-muted hover:text-tv-text px-4 py-2 text-lg">
            {{ link.label }}
          </a>
        </div>
      </div>
      <div class="flex items-center gap-4 text-base">
        <a href="/settings" class="text-tv-blue hover:text-tv-text px-3 py-1 border border-tv-blue rounded text-sm">
          <i class="fas fa-cog mr-1"></i>Settings
        </a>
      </div>
    </div>
  </nav>

  <!-- Main Content -->
  <div class="max-w-3xl mx-auto px-6 py-10">
    <h1 class="text-2xl font-bold text-tv-text mb-2">
      <i class="fas fa-shield-halved mr-2 text-tv-blue"></i>Privacy & Data Practices
    </h1>
    <p class="text-tv-muted text-sm mb-8">
      How OptionLedger handles your Tastytrade data
    </p>

    <!-- What We Access -->
    <section class="bg-tv-panel border border-tv-border rounded mb-5">
      <div class="px-5 py-4 border-b border-tv-border">
        <h2 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-download mr-2 text-tv-blue"></i>What we access from Tastytrade
        </h2>
      </div>
      <div class="p-5 text-sm text-tv-text space-y-3">
        <p class="text-tv-muted">
          When you connect your Tastytrade account, OptionLedger accesses the following data through the Tastytrade API:
        </p>
        <ul class="space-y-2 ml-1">
          <li class="flex items-start gap-2">
            <i class="fas fa-wallet text-tv-blue w-5 text-center mt-0.5"></i>
            <span><strong>Account information</strong> &mdash; account numbers, account names, and current balances</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-receipt text-tv-blue w-5 text-center mt-0.5"></i>
            <span><strong>Transaction history</strong> &mdash; all historical trades, assignments, expirations, and exercises</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-chart-pie text-tv-blue w-5 text-center mt-0.5"></i>
            <span><strong>Current positions</strong> &mdash; open option and equity positions with quantities and cost basis</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-bolt text-tv-blue w-5 text-center mt-0.5"></i>
            <span><strong>Real-time quotes</strong> &mdash; live market prices for your current holdings, streamed via WebSocket</span>
          </li>
        </ul>
        <p class="text-tv-muted text-xs mt-3">
          All access is <strong class="text-tv-text">read-only</strong>. OptionLedger cannot place trades, transfer funds, or modify your Tastytrade account in any way.
        </p>
      </div>
    </section>

    <!-- What We Store -->
    <section class="bg-tv-panel border border-tv-border rounded mb-5">
      <div class="px-5 py-4 border-b border-tv-border">
        <h2 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-database mr-2 text-tv-green"></i>What we store
        </h2>
      </div>
      <div class="p-5 text-sm text-tv-text space-y-3">
        <ul class="space-y-2 ml-1">
          <li class="flex items-start gap-2">
            <i class="fas fa-lock text-tv-green w-5 text-center mt-0.5"></i>
            <span><strong>Encrypted connection token</strong> &mdash; your Tastytrade OAuth refresh token, encrypted at rest with Fernet symmetric encryption. Your password is never stored.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-list text-tv-green w-5 text-center mt-0.5"></i>
            <span><strong>Transaction history</strong> &mdash; imported trades, positions, and account balances are stored in the database for analysis and display.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-clock text-tv-green w-5 text-center mt-0.5"></i>
            <span><strong>Cached market quotes</strong> &mdash; recent price data is cached temporarily (30-second TTL) to reduce API calls. Not persisted long-term.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-sticky-note text-tv-green w-5 text-center mt-0.5"></i>
            <span><strong>User-created content</strong> &mdash; notes, tags, strategy targets, and settings you configure within the app.</span>
          </li>
        </ul>
        <p class="text-tv-muted text-xs mt-3">
          All stored data is scoped to your user account with per-user data isolation. No other user can see your data.
        </p>
      </div>
    </section>

    <!-- What We Don't Store or Share -->
    <section class="bg-tv-panel border border-tv-border rounded mb-5">
      <div class="px-5 py-4 border-b border-tv-border">
        <h2 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-ban mr-2 text-tv-red"></i>What we do NOT store or share
        </h2>
      </div>
      <div class="p-5 text-sm text-tv-text space-y-3">
        <ul class="space-y-2 ml-1">
          <li class="flex items-start gap-2">
            <i class="fas fa-key text-tv-red w-5 text-center mt-0.5"></i>
            <span><strong>Your Tastytrade password</strong> &mdash; we never see or store your password. Authentication uses OAuth2 tokens only.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-users-slash text-tv-red w-5 text-center mt-0.5"></i>
            <span><strong>No third-party data sharing</strong> &mdash; your trading data is never shared with, sold to, or accessible by any third party.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-share-nodes text-tv-red w-5 text-center mt-0.5"></i>
            <span><strong>No market data redistribution</strong> &mdash; real-time quotes and market data are used solely for your personal display and are never redistributed.</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- Data Retention -->
    <section class="bg-tv-panel border border-tv-border rounded mb-5">
      <div class="px-5 py-4 border-b border-tv-border">
        <h2 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-calendar-days mr-2 text-tv-muted"></i>Data retention
        </h2>
      </div>
      <div class="p-5 text-sm text-tv-text space-y-2">
        <p>Your trading data is retained for as long as your account is active. Cached market quotes expire automatically (30-second TTL) and are not stored permanently.</p>
        <p class="text-tv-muted">If you disconnect your Tastytrade account via Settings, your OAuth token is immediately deleted. Your imported transaction history remains available until you explicitly delete it.</p>
      </div>
    </section>

    <!-- How to Delete Your Data -->
    <section class="bg-tv-panel border border-tv-border rounded mb-5">
      <div class="px-5 py-4 border-b border-tv-border">
        <h2 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-trash-alt mr-2 text-tv-muted"></i>How to delete your data
        </h2>
      </div>
      <div class="p-5 text-sm text-tv-text space-y-2">
        <ul class="space-y-2 ml-1">
          <li class="flex items-start gap-2">
            <i class="fas fa-unlink text-tv-muted w-5 text-center mt-0.5"></i>
            <span><strong>Disconnect Tastytrade</strong> &mdash; go to <a href="/settings" class="text-tv-blue hover:underline">Settings</a> and click "Disconnect" to remove your OAuth credentials.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-database text-tv-muted w-5 text-center mt-0.5"></i>
            <span><strong>Delete trade data</strong> &mdash; use the "Initial Sync" feature in <a href="/settings" class="text-tv-blue hover:underline">Settings</a> to clear and rebuild the database, or contact us for full account deletion.</span>
          </li>
          <li class="flex items-start gap-2">
            <i class="fas fa-rotate-left text-tv-muted w-5 text-center mt-0.5"></i>
            <span><strong>Revoke access on Tastytrade</strong> &mdash; you can also revoke OptionLedger's access directly from your Tastytrade account at my.tastytrade.com under Manage &rarr; My Profile &rarr; API &rarr; OAuth Applications.</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- Contact -->
    <section class="bg-tv-panel border border-tv-border rounded mb-10">
      <div class="px-5 py-4 border-b border-tv-border">
        <h2 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-envelope mr-2 text-tv-muted"></i>Contact
        </h2>
      </div>
      <div class="p-5 text-sm text-tv-text">
        <p>
          If you have questions about our data practices or want to request data deletion, please contact us at
          <a href="mailto:support@optionledger.com" class="text-tv-blue hover:underline">support@optionledger.com</a>.
        </p>
      </div>
    </section>

    <!-- Footer -->
    <div class="text-center text-tv-muted text-xs pb-8">
      &copy; {{ new Date().getFullYear() }} OptionLedger. All rights reserved.
    </div>
  </div>
</template>
