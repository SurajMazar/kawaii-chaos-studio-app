import { create } from 'zustand'
import { api, setCsrf } from './api'
import type { AuthState, Role, User } from './types'

const LEVEL: Record<Role, number> = { viewer: 0, editor: 1, admin: 2 }

interface AuthStore {
  state: AuthState | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  setUser: (u: User | null, csrf?: string) => void
}

export const useAuth = create<AuthStore>((set, get) => ({
  state: null, loading: true, error: null,
  refresh: async () => {
    try {
      const s = await api.authState(); setCsrf(s.csrf)
      set({ state: s, loading: false, error: null })
    } catch (e) { set({ loading: false, error: (e as Error).message }) }
  },
  setUser: (u, csrf) => {
    if (csrf) setCsrf(csrf)
    const s = get().state
    if (s) set({ state: { ...s, user: u, setup_required: false, setup_token_required: false, csrf: csrf ?? s.csrf } })
  },
}))

export function useUser() { return useAuth(s => s.state?.user ?? null) }

/** true when the signed-in user has at least this role */
export function useCan(role: Role) {
  const u = useUser()
  return !!u && LEVEL[u.role] >= LEVEL[role]
}

export const roleLabel: Record<Role, string> = { viewer: 'Viewer (read only)', editor: 'Editor', admin: 'Admin' }
export const roleColor: Record<Role, string> = { viewer: 'default', editor: 'blue', admin: 'magenta' }
