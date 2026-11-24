import { useQueries } from '@tanstack/react-query';
import { getDocumentStatus } from '@/api/documents';
import type { DocumentStatus, DocumentStatusResponse } from '@/types/document';

const TERMINAL: DocumentStatus[] = ['ready', 'failed'];

/**
 * 对需要追踪的文档按 2 秒轮询状态；进入终态即停止，避免全表空转。
 * onResult 在每次状态返回时触发，供调用方失效列表或清理乐观记录。
 */
export function useDocumentPolling(
  processingIds: string[],
  intervalMs = 2000,
  onResult?: (documentId: string, status: DocumentStatusResponse) => void,
) {
  return useQueries({
    queries: processingIds.map((id) => ({
      queryKey: ['document-status', id],
      queryFn: async () => {
        const data = await getDocumentStatus(id);
        onResult?.(id, data);
        return data;
      },
      refetchInterval: (query: { state: { data?: { status: DocumentStatus } } }) =>
        query.state.data && TERMINAL.includes(query.state.data.status) ? false : intervalMs,
      refetchIntervalInBackground: false,
      staleTime: 0,
    })),
  });
}
