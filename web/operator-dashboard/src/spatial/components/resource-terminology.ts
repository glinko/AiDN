export const RESOURCE_TERMINOLOGY = {
  balance: 'Resources',
  contribution: 'Resource Contribution',
  credit: 'Contribution Credit',
  usage: 'Resource Usage',
  settlement: 'Resource Settlement',
  cost: 'Resource Cost',
  credits: 'Contribution Credits',
} as const

export const FORBIDDEN_RESOURCE_TERMS = ['Money', 'Income', 'Spending', 'Revenue', 'Payment', 'Price', 'Earnings'] as const

export function assertCanonicalResourceCopy(copy: string): void {
  const found = FORBIDDEN_RESOURCE_TERMS.find((term) => new RegExp(`\\b${term}\\b`, 'i').test(copy))
  if (found) throw new Error(`resource copy uses forbidden fiat term: ${found}`)
}

export function formatQAtoms(qAtoms: string): string {
  if (!/^-?\d+$/.test(qAtoms)) throw new Error('q_atoms must be an exact integer string')
  return `${qAtoms} Q`
}
