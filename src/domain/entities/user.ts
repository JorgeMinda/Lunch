export type UserRole = 'admin' | 'parent' | 'canteen'

export interface User {
  id: string
  email: string
  role: UserRole
  name: string
}

export type Profile = User
