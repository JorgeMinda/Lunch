export type TransactionStatus = 'pending' | 'approved'

export interface Transaction {
  id: string
  studentId: string
  parentId: string
  amount: number
  receiptUrl: string
  status: TransactionStatus
  createdAt: string
  approvedAt: string | null
}
