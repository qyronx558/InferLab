import { createContext } from 'react';
import type { SessionInfo } from '@/api/client';

export const sessionKey = ['live', 'session'] as const;

export interface AuthValue {
  session: SessionInfo | null;
  isLoading: boolean;
  error: unknown;
  retry: () => void;
  login: (password: string) => Promise<SessionInfo>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthValue | null>(null);
