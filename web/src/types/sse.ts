import type { Citation } from './document';
import type { Confidence, StopReason } from './ask';

/**
 * SSE 事件，字段与 prd/05-api-spec.md §4.2 逐一对齐。
 *
 * 注意：API-7 是 POST，原生 EventSource 只支持 GET 且无法自定义请求头，
 * 因此必须使用 @microsoft/fetch-event-source。
 */
export type ResearchEvent =
  | {
      type: 'started';
      agent_run_id: string;
      session_id: string;
      question: string;
      max_iterations: number;
    }
  | {
      type: 'iteration';
      iteration: number;
      queries: string[];
      searched_query_count: number;
    }
  | {
      type: 'retrieved';
      iteration: number;
      retrieved_chunk_count: number;
      new_chunk_count: number;
      max_score: number;
    }
  | {
      type: 'reasoning';
      iteration: number;
      decision: 'continue' | 'answer';
      reason: string;
      missing_information: string;
      findings_count: number;
      conflicts_count: number;
    }
  | {
      type: 'final_answer';
      agent_run_id: string;
      answer: string;
      confidence: Confidence;
      stop_reason: StopReason;
      iteration_count: number;
      duration_ms: number;
      token_used: number;
      citations: Citation[];
    }
  | {
      type: 'error';
      code: string;
      message: string;
      trace_id: string;
    };

/** 调研过程中的单个时间线节点（由事件聚合而来） */
export interface TimelineNode {
  iteration: number;
  queries: string[];
  retrieved_chunk_count?: number;
  new_chunk_count?: number;
  max_score?: number;
  decision?: 'continue' | 'answer';
  reason?: string;
  missing_information?: string;
  loading: boolean;
}
