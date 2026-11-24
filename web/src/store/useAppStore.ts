import { create } from 'zustand';
import type { Session } from '@/types/session';

type StoredSession = Pick<Session, 'session_id' | 'title' | 'default_document_ids' | 'created_at'>;

const SESSION_STORAGE_KEY = 'alethix:current-session';

function loadStoredSession(): StoredSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredSession;
  } catch (error) {
    console.error('[store] 读取会话状态失败', error);
    return null;
  }
}

function saveStoredSession(session: StoredSession | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (session) {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } else {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }
  } catch (error) {
    console.error('[store] 保存会话状态失败', error);
  }
}

interface AppState {
  /** 当前会话 ID */
  currentSessionId: string | null;
  /** 当前会话对象，用于展示该会话创建时的检索范围 */
  currentSession: StoredSession | null;
  /** 当前检索范围；为空表示全部文档 */
  selectedDocIds: string[];
  setCurrentSessionId: (id: string | null) => void;
  setCurrentSession: (session: StoredSession | null) => void;
  setSelectedDocIds: (ids: string[]) => void;
  toggleDocId: (id: string) => void;
  removeDocId: (id: string) => void;
}

const initialSession = loadStoredSession();

/** 仅承载跨页面的轻量 UI 状态；服务端数据归 TanStack Query */
export const useAppStore = create<AppState>((set) => ({
  currentSessionId: initialSession?.session_id ?? null,
  currentSession: initialSession,
  selectedDocIds: [],
  setCurrentSessionId: (id) =>
    set((state) => ({
      currentSessionId: id,
      currentSession: state.currentSession?.session_id === id ? state.currentSession : null,
    })),
  setCurrentSession: (session) => {
    saveStoredSession(session);
    set({
      currentSession: session,
      currentSessionId: session?.session_id ?? null,
    });
  },
  setSelectedDocIds: (ids) => set({ selectedDocIds: ids }),
  toggleDocId: (id) =>
    set((state) => ({
      selectedDocIds: state.selectedDocIds.includes(id)
        ? state.selectedDocIds.filter((item) => item !== id)
        : [...state.selectedDocIds, id],
    })),
  removeDocId: (id) =>
    set((state) => ({
      selectedDocIds: state.selectedDocIds.filter((item) => item !== id),
    })),
}));
