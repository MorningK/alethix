import { useQuery } from '@tanstack/react-query';
import { listMessages } from '@/api/sessions';
import type { Paginated, Message } from '@/types/session';

/** 加载会话历史消息（API-8） */
export function useSessionMessages(sessionId: string | null) {
  return useQuery<Paginated<Message>>({
    queryKey: ['messages', sessionId],
    queryFn: () => listMessages(sessionId as string),
    enabled: Boolean(sessionId),
    staleTime: 10_000,
  });
}
