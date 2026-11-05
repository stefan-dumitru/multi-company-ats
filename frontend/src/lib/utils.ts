import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Joins class names and resolves Tailwind conflicts: cn('p-2', 'p-4') gives 'p-4', not both.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
