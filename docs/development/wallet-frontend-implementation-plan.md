# AiDN Wallet Workspace and Transfer Flow

Status: Implementation slice

Version: 0.1

## Purpose

The Wallet workspace is the operator's control surface for the node Owner
Wallet. It must show the difference between local projections and canonical
network state, make every mutating action explicit, and never imply that a
browser-side balance change is a payment.

The page is a control surface over existing Hypervisor and Ledger services. It
is not a second wallet implementation and it never receives or stores a
private key after wallet bootstrap/import.

## Page Responsibilities

The Wallet page is organized into these sections:

1. **Ownership and binding**
   - Show the configured Owner Wallet label, shortened wallet ID, binding state
     and public identity state.
   - Explain whether the displayed balance comes from the consensus quorum,
     a consensus projection or an unverified local projection.
   - Keep wallet creation/import and network identity registration as separate
     actions with their own visible result states.

2. **Balance and network status**
   - Show canonical `q_atoms` and the formatted Q value.
   - Show balance source and any reconciliation error.
   - Show pending operation count and the amount currently waiting for
     consensus finality.
   - A refresh must replace the read model and must not fabricate a success
     notice.

3. **Wallet transfer**
   - MVP sender: the node's configured Owner Wallet only.
   - Recipient: an explicit Wallet ID entered by the operator.
   - Amount: entered in Q for usability and converted to integer `q_atoms`
     without binary floating-point arithmetic.
   - Optional memo: retained as a hash in the Ledger payload; private memo
     text is not put into the canonical operation.
   - `Preview transfer` validates the form and returns the sender, recipient,
     amount, network fee, total debit, available balance, sender sequence and
     whether consensus is required. Preview has no Ledger side effect.
   - `Submit transfer` is enabled only after a current preview. The server
     creates and signs a canonical `WALLET_TRANSFER` envelope and submits it
     through the configured consensus service on validator nodes.
   - The page displays `FINALIZED`, `CONSENSUS_PENDING` or a rejection with
     the operation ID and the current finality evidence.
   - A pending transfer is listed after refresh. A failed CheckTx can be
     retried by submitting a fresh envelope for the same sequence; a pending
     non-failed operation is never duplicated by a browser retry.

4. **Ledger activity**
   - Show finalized wallet ledger events, including transfer operation ID,
     recipient, amount, fee and timestamp.
   - Show pending transfers separately from finalized activity.
   - Display operation IDs in shortened form with a copy action where the
     existing UI pattern supports it.
   - Activity is evidence from the Hypervisor read model, not optimistic UI
     state.

5. **Usage, allocation and disputes**
   - Keep usage, allocation and dispute journals visible as separate streams.
   - These records explain why a balance changed but do not provide an
     operator-side shortcut around Settlement or consensus.

6. **Economics and faucet boundary**
   - Show recyclable fees/removals and the faucet preview as separate sources.
   - The faucet remains an external Treasury service. The Wallet page must
     not represent an unconfirmed faucet claim as local balance.

## Transfer Contract

### Request

```json
{
  "recipient_wallet": "wallet-recipient",
  "amount_q_atoms": 2500000,
  "memo": "optional operator note"
}
```

The request is accepted only through the paired operator Dashboard session.
The browser never supplies the sender Wallet ID or a signing key; the server
derives both from the configured Owner Wallet.

### Preview

`POST /operators/dashboard/access/operations/wallet/transfer/preview`

Preview returns:

- `amount_q_atoms`;
- `network_fee_q_atoms`;
- `total_debit_q_atoms`;
- `available_balance_q_atoms`;
- `sufficient_balance`;
- `sender_sequence`;
- `consensus_required`;
- `memo_hash` when a memo was supplied.

It does not reserve funds, increment a sequence or stage an operation.

### Submit

`POST /operators/dashboard/access/operations/wallet/transfer`

The operation uses:

- `operation_type = WALLET_TRANSFER`;
- `origin_type = wallet`;
- `fee_class = standard`;
- the canonical sender sequence;
- the standard network fee defined by the Ledger service;
- the Owner Wallet signature.

The Ledger validates recipient separation, integer amount, available balance,
replay protection and sequence. Validator nodes are not allowed to accept
this browser mutation through a local non-consensus path.

### Response states

| State | Meaning | Operator action |
| --- | --- | --- |
| `FINALIZED` | The operation is in the canonical Ledger/finality projection. | Refresh or inspect activity. |
| `CONSENSUS_PENDING` | The envelope was submitted and is awaiting quorum/finality. | Wait and refresh; do not submit a duplicate. |
| HTTP `409` | CheckTx or local validation rejected the operation. | Read the rejection, correct the input or network state, then retry. |

## Safety Rules

- No optimistic balance decrement is rendered before finality.
- A rejected operation is not treated as configured or paid.
- A pending operation is idempotent for the same semantic intent and sender
  sequence.
- A different operation already occupying the sender sequence blocks a second
  transfer until the first operation is resolved.
- The UI never exposes the private key in a read-model response.
- Canonical integer accounting uses `q_atoms`; display formatting is cosmetic.
- Ownership transfer, arbitrary source Wallet selection, multisignature
  policies and recurring payments remain separate future protocols.

## Acceptance Criteria

- An operator can preview a transfer and see the exact fee and total debit.
- Preview does not change balance, sequence or Ledger operation count.
- Submit on a consensus-enabled node produces a signed `WALLET_TRANSFER` and
  reports pending/finalized/rejected explicitly.
- Validator middleware allows only the bounded transfer routes and the
  operation still enters consensus.
- Refresh shows pending transfers and finalized transfer activity from the
  server read model.
- Insufficient balance, self-transfer, invalid amount and stale sequence are
  visible as actionable errors.
- Frontend build and backend transfer tests pass.

## Follow-up Work

- Add a dedicated operation-detail drawer with evidence and quorum receipts.
- Add recipient address book entries only after an identity/discovery policy
  exists.
- Add signed ownership transfer and multisignature authorization flows.
- Add scheduled/recurring transfers only as a separate Ledger operation type.
- Add export/download of the Wallet ledger evidence bundle.
