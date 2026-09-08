import type { Citation } from './document';
import type { Confidence } from './ask';

/** 会话，对应 DM-4 */
export interface Session {
  session_id: string;
  title: string | null;
  default_document_ids: string[];
  message_count: number;
  created_at?: string;
}

/** 会话消息，对应 DM-5 / API-8 */
export interface Message {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  agent_run_id: string | null;
  confidence?: Confidence;
  citations?: Citation[];
}

/** 分页响应，对应 prd/05-api-spec.md §1.3 */
export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
