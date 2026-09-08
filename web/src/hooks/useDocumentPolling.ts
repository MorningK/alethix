import { useQueries } from '@tanstack/react-query';
import { getDocumentStatus } from '@/api/documents';
import type { DocumentStatus } from '@/types/document';

const TERMINAL: DocumentStatus[] = ['ready', 'failed'];

/**
 * 对「非终态」文档按 2 秒轮询状态（FE-F1-2）。
 * 进入终态即停止，避免全表空转。
 */
export function useDocumentPolling(processingIds: string[], intervalMs = 2000) {
  return useQueries({
    queries: processingIds.map((id) => ({
      queryKey: ['document-status', id],
      queryFn: () => getDocumentStatus(id),
      refetchInterval: (query: { state: { data?: { status: DocumentStatus } } }) =>
        query.state.data && TERMINAL.includes(query.state.data.status) ? false : intervalMs,
      refetchIntervalInBackground: false,
      staleTime: 0,
    })),
  });
}
