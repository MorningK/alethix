import type { Citation } from './document';

/** 终止原因，与 prd/03-agent-design.md §5 的 StopReason 枚举一致 */
export type StopReason =
  | 'sufficient'
  | 'max_iterations_reached'
  | 'no_new_queries'
  | 'no_new_evidence'
  | 'low_relevance'
  | 'budget_exceeded'
  | 'internal_error';

export type Confidence = 'high' | 'medium' | 'low';

/** 单轮迭代记录，对应 prd/05-api-spec.md §2.3 */
export interface IterationRecord {
  iteration: number;
  queries: string[];
  retrieved_chunk_count: number;
  new_chunk_count: number;
  findings: string[];
  conflicts: string[];
  decision: 'continue' | 'answer';
  reason: string;
  missing_information?: string;
}

/** 问答请求，对应 API-6 / API-7 */
export interface AskRequest {
  session_id: string;
  question: string;
  document_ids?: string[];
  max_iterations?: number;
}

/** 问答响应，对应 API-6 */
export interface AskResponse {
  agent_run_id: string;
  session_id: string;
  question: string;
  answer: string;
  confidence: Confidence;
  stop_reason: StopReason | null;
  iteration_count: number;
  duration_ms?: number;
  token_used?: number;
  iterations: IterationRecord[];
  citations: Citation[];
}
