import { useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { listMessages } from '@/api/sessions';
import type { Message } from '@/types/session';

const PAGE_SIZE = 20;

function byMessageId(a: Message, b: Message): number {
  return Number(a.message_id) - Number(b.message_id);
}

interface PaginationState {
  key: string;
  olderItems: Message[];
  oldestLoadedPage: number;
}

/** 加载会话历史：默认展示最新一页，并支持加载更早消息。 */
export function useSessionMessages(sessionId: string | null) {
  const queryClient = useQueryClient();
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [pagination, setPagination] = useState<PaginationState>({
    key: '',
    olderItems: [],
    oldestLoadedPage: 1,
  });

  const metaQuery = useQuery({
    queryKey: ['messages', sessionId, 'meta'],
    queryFn: () => listMessages(sessionId as string, { page: 1, page_size: 1 }),
    enabled: Boolean(sessionId),
    staleTime: 10_000,
  });

  const latestPage = Math.max(1, Math.ceil((metaQuery.data?.total ?? 0) / PAGE_SIZE));
  const paginationKey = `${sessionId ?? ''}:${latestPage}`;
  const activePagination: PaginationState =
    pagination.key === paginationKey
      ? pagination
      : { key: paginationKey, olderItems: [], oldestLoadedPage: latestPage };

  const messagesQuery = useQuery({
    queryKey: ['messages', sessionId, 'page', latestPage, PAGE_SIZE],
    queryFn: () => listMessages(sessionId as string, { page: latestPage, page_size: PAGE_SIZE }),
    enabled: Boolean(sessionId) && metaQuery.isSuccess,
    staleTime: 10_000,
  });

  const refetchHistory = useCallback(async () => {
    if (!sessionId) return { items: [] as Message[], total: 0 };
    await queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
    const meta = await queryClient.fetchQuery({
      queryKey: ['messages', sessionId, 'meta'],
      queryFn: () => listMessages(sessionId, { page: 1, page_size: 1 }),
      staleTime: 0,
    });
    const page = Math.max(1, Math.ceil(meta.total / PAGE_SIZE));
    const result = await queryClient.fetchQuery({
      queryKey: ['messages', sessionId, 'page', page, PAGE_SIZE],
      queryFn: () => listMessages(sessionId, { page, page_size: PAGE_SIZE }),
      staleTime: 0,
    });
    return { items: result.items, total: meta.total };
  }, [queryClient, sessionId]);

  const loadOlder = async () => {
    const oldestLoadedPage = activePagination.oldestLoadedPage;
    if (!sessionId || oldestLoadedPage <= 1 || loadingOlder) return;
    const page = oldestLoadedPage - 1;
    setLoadingOlder(true);
    try {
      const result = await listMessages(sessionId, { page, page_size: PAGE_SIZE });
      setPagination((prev) => {
        const current =
          prev.key === paginationKey
            ? prev
            : { key: paginationKey, olderItems: [], oldestLoadedPage };
        const seen = new Set(current.olderItems.map((item) => item.message_id));
        const olderItems = [
          ...result.items.filter((item) => !seen.has(item.message_id)),
          ...current.olderItems,
        ].toSorted(byMessageId);
        return { key: paginationKey, olderItems, oldestLoadedPage: page };
      });
    } finally {
      setLoadingOlder(false);
    }
  };

  const items = [...activePagination.olderItems, ...(messagesQuery.data?.items ?? [])].toSorted(
    byMessageId,
  );

  return {
    items,
    total: metaQuery.data?.total ?? 0,
    page: latestPage,
    isLoading: metaQuery.isLoading || messagesQuery.isLoading,
    isError: metaQuery.isError || messagesQuery.isError,
    hasOlder: activePagination.oldestLoadedPage > 1,
    loadOlder,
    loadingOlder,
    refetchHistory,
  };
}
