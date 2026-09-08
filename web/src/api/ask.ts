import { http } from './http';
import type { AskRequest, AskResponse } from '@/types/ask';

/** API-6 同步问答（SSE 不可用时的兜底） */
export async function askSync(payload: AskRequest) {
  const { data } = await http.post<AskResponse>('/ask', payload);
  return data;
}
