import { useCallback, useEffect, useRef, useState } from 'react';
import { askStream } from '@/api/sse';
import type { AskRequest } from '@/types/ask';
import type { FinalAnswerEvent, ResearchEvent, TimelineNode } from '@/types/sse';

interface StreamState {
  timeline: TimelineNode[];
  running: boolean;
  error: string | null;
  finalAnswer: FinalAnswerEvent | null;
  currentQuestion: string | null;
  aborted: boolean;
}

/**
 * 调研流：按轮次把事件聚合为时间线节点（FE-F2-1）。
 * 中间态只存组件本地 state，final_answer 到达后再由调用方写入 Query 缓存。
 */
export function useAskStream() {
  const controllerRef = useRef<AbortController | null>(null);
  const lastEventIdRef = useRef<number | null>(null);
  const [state, setState] = useState<StreamState>({
    timeline: [],
    running: false,
    error: null,
    finalAnswer: null,
    currentQuestion: null,
    aborted: false,
  });

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState((prev) => ({ ...prev, running: false, aborted: true }));
  }, []);

  const start = useCallback((payload: AskRequest, onFinal?: (event: FinalAnswerEvent) => void) => {
    controllerRef.current?.abort();
    lastEventIdRef.current = null;
    setState({
      timeline: [],
      running: true,
      error: null,
      finalAnswer: null,
      currentQuestion: payload.question,
      aborted: false,
    });

    controllerRef.current = askStream(payload, {
      onEvent: (event: ResearchEvent, eventId?: number) => {
        if (eventId) lastEventIdRef.current = eventId;

        if (event.type === 'error') {
          setState((prev) => ({ ...prev, running: false, error: event.message }));
          return;
        }

        if (event.type === 'iteration') {
          setState((prev) => ({
            ...prev,
            timeline: [
              ...prev.timeline,
              {
                iteration: event.iteration,
                queries: event.queries,
                loading: true,
              },
            ],
          }));
          return;
        }

        if (event.type === 'retrieved' || event.type === 'reasoning') {
          setState((prev) => {
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
                    findings_count: event.findings_count,
                    conflicts_count: event.conflicts_count,
                    loading: false,
                  };
            return { ...prev, timeline: [...prev.timeline.slice(0, -1), merged] };
          });
          return;
        }

        if (event.type === 'final_answer') {
          setState((prev) => ({
            ...prev,
            running: false,
            finalAnswer: event,
            timeline: prev.timeline.map((node) => ({ ...node, loading: false })),
          }));
          onFinal?.(event);
        }
      },
      onError: (message) => {
        setState((prev) => ({ ...prev, running: false, error: message }));
      },
      onClose: () => {
        setState((prev) => ({
          ...prev,
          running: false,
          aborted: prev.running && !prev.finalAnswer && !prev.error,
        }));
      },
    });
  }, []);

  const reset = useCallback(() => {
    lastEventIdRef.current = null;
    setState({
      timeline: [],
      running: false,
      error: null,
      finalAnswer: null,
      currentQuestion: null,
      aborted: false,
    });
  }, []);

  const settle = useCallback(() => {
    setState((prev) => ({
      ...prev,
      running: false,
      finalAnswer: null,
      currentQuestion: null,
    }));
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return { ...state, start, stop, reset, settle };
}
