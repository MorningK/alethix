import { create } from 'zustand';

interface AppState {
  /** 当前会话 ID */
  currentSessionId: string | null;
  /** 当前检索范围；为空表示全部文档 */
  selectedDocIds: string[];
  setCurrentSessionId: (id: string | null) => void;
  setSelectedDocIds: (ids: string[]) => void;
  toggleDocId: (id: string) => void;
}

/** 仅承载跨页面的轻量 UI 状态；服务端数据归 TanStack Query */
export const useAppStore = create<AppState>((set) => ({
  currentSessionId: null,
  selectedDocIds: [],
  setCurrentSessionId: (id) => set({ currentSessionId: id }),
  setSelectedDocIds: (ids) => set({ selectedDocIds: ids }),
  toggleDocId: (id) =>
    set((state) => ({
      selectedDocIds: state.selectedDocIds.includes(id)
        ? state.selectedDocIds.filter((item) => item !== id)
        : [...state.selectedDocIds, id],
    })),
}));
