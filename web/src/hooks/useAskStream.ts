import { useCallback, useRef, useState } from 'react';
import { askStream } from '@/api/sse';
import type { AskRequest } from '@/types/ask';
import type { TimelineNode } from '@/types/sse';

interface StreamState {
  timeline: TimelineNode[];
  running: boolean;
  error: string | null;
}

/**
 * 调研流：按轮次把事件聚合为时间线节点（FE-F2-1）。
 * 中间态只存组件本地 state，final_answer 到达后再由调用方写入 Query 缓存。
 */
export function useAskStream() {
  const controllerRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<StreamState>({
    timeline: [],
    running: false,
    error: null,
  });

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState((prev) => ({ ...prev, running: false }));
  }, []);

  const start = useCallback((payload: AskRequest, onFinal: () => void) => {
    controllerRef.current?.abort();
    setState({ timeline: [], running: true, error: null });

    controllerRef.current = askStream(payload, {
      onEvent: (event) => {
        setState((prev) => {
          if (event.type === 'iteration') {
            return {
              ...prev,
              timeline: [
                ...prev.timeline,
                {
                  iteration: event.iteration,
                  queries: event.queries,
                  loading: true,
                },
              ],
            };
          }

          if (event.type === 'retrieved' || event.type === 'reasoning') {
            const last = prev.timeline[prev.timeline.length - 1];
            if (!last) return prev;
            const merged: TimelineNode =
              event.type === 'retrieved'
                ? {
                    ...last,
                    retrieved_chunk_count: event.retrieved_chunk_count,
                    new_chunk_count: event.new_chunk_count,
                    max_score: event.max_score,
                  }
                : {
                    ...last,
                    decision: event.decision,
                    reason: event.reason,
                    missing_information: event.missing_information,
                    loading: false,
                  };
            return { ...prev, timeline: [...prev.timeline.slice(0, -1), merged] };
          }

          if (event.type === 'final_answer') {
            return {
              ...prev,
              running: false,
              timeline: prev.timeline.map((n) => ({ ...n, loading: false })),
            };
          }

          return prev;
        });

        if (event.type === 'final_answer') {
          onFinal();
        }
      },
      onError: (message) => {
        setState((prev) => ({ ...prev, running: false, error: message }));
      },
      onClose: () => {
        setState((prev) => ({ ...prev, running: false }));
      },
    });
  }, []);

  return { ...state, start, stop };
}
