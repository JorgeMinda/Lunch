export type WeekDay =
  | 'monday'
  | 'tuesday'
  | 'wednesday'
  | 'thursday'
  | 'friday'

export const WEEK_DAYS: readonly WeekDay[] = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
] as const

export interface MenuDay {
  day: WeekDay
  description: string
}

export interface Menu {
  id: string
  weekStartDate: string
  days: MenuDay[]
  isActive: boolean
}
