import { http } from './http';
import type { Message, Paginated, Session } from '@/types/session';

/** API-1 创建会话 */
export async function createSession(params: { title?: string; default_document_ids?: string[] }) {
  const { data } = await http.post<Session>('/sessions', params);
  return data;
}

/** API-8 会话历史（按时间正序） */
export async function listMessages(
  sessionId: string,
  params: { page?: number; page_size?: number } = {},
) {
  const { data } = await http.get<Paginated<Message>>(`/sessions/${sessionId}/messages`, {
    params,
  });
  return data;
}
