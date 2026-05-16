\echo === Post-reprocess chain summaries ===
SELECT id, account_number, chain_length, roll_count, cumulative_premium, cumulative_realized_pnl
FROM roll_chain_summaries
WHERE user_id='fe3a93df-3714-4f0c-98de-a4c030ae8e44'
  AND underlying='IBIT'
  AND first_opened >= '2026-02-01'
ORDER BY first_opened, account_number;
