# Solana devnet setup for record_settlement (SPEC section 14)

`record_settlement` writes an audit log of simulated curtailment events
on Solana devnet. There is no production token and no real money
involved — devnet SOL is a free faucet token used only so transaction
signatures and Explorer links are real.

## 1. Create a devnet-only keypair

```bash
solana-keygen new --outfile ~/.config/gridpulse/devnet-keypair.json
```

Always create a NEW keypair for this. Never reuse a keypair that holds
real funds on any cluster. The file is a 64-byte JSON array; keep it
out of git (it is already covered by `.gitignore` patterns for
`*keypair*.json` — verify with `git check-ignore`).

## 2. Airdrop devnet SOL

```bash
solana airdrop 1 --keypair ~/.config/gridpulse/devnet-keypair.json \
  --url https://api.devnet.solana.com
```

Or use the web faucet at https://faucet.solana.com with the address
printed by `solana-keygen pubkey ~/.config/gridpulse/devnet-keypair.json`.
The public RPC may rate-limit airdrops (HTTP 429); retry later or use
the web faucet. One signature-only memo transaction costs ~5000
lamports, so 0.1 SOL is plenty for a demo.

## 3. Install the signing library

```bash
backend/.local/venv/bin/python -m pip install solders==0.29.0
```

`solders` provides the keypair/transaction primitives. It is imported
lazily inside the live path, so `SOLANA_MODE=mock` works without it.

## 4. Environment variables

```
SOLANA_MODE=live
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_KEYPAIR_PATH=/absolute/path/to/devnet-keypair.json
```

`SOLANA_MODE=mock` (the default) opens no socket and returns
`mocksig-` plus 16 hex chars of SHA-256(schedule_id).

## 5. Verify

After approving a schedule, the decision feed shows `settlement_tx`
with `mode live` and a `signature`; open

```
https://explorer.solana.com/tx/<signature>?cluster=devnet
```

to confirm. The transaction contains one SPL Memo instruction whose
UTF-8 payload is the section-14 memo JSON.

## 6. Failure behavior

The send runs on a background thread with a 10-second timeout and no
retry. Any failure logs an `error` row with `integration` `solana`;
the applied schedule stays applied.
