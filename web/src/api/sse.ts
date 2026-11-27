import { fetchEventSource } from '@microsoft/fetch-event-source';
import type { AskRequest } from '@/types/ask';
import type { ResearchEvent } from '@/types/sse';

const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const devUserId = import.meta.env.VITE_USER_ID ?? '';
const MAX_RETRIES = 3;

export interface StreamHandlers {
  onEvent: (event: ResearchEvent, eventId?: number) => void;
  onError?: (message: string, code?: string) => void;
  onClose?: () => void;
}

/**
 * 发起流式问答（API-7）。
 *
 * 为什么不用原生 EventSource：
 *   1. API-7 是 POST，而 EventSource 只支持 GET，无法携带请求体
 *   2. 所有接口都要求 X-User-Id 请求头，而 EventSource 无法自定义请求头
 * 因此统一使用 @microsoft/fetch-event-source（基于 fetch）。
 */
export function askStream(payload: AskRequest, handlers: StreamHandlers): AbortController {
  const controller = new AbortController();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(devUserId ? { 'X-User-Id': devUserId } : {}),
  };
  let retries = 0;
  let fatal = false;

  fetchEventSource(`${baseURL}/ask/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal: controller.signal,

    async onopen(response) {
      if (!response.ok) {
        fatal = response.status < 500;
        const text = await response.text().catch(() => '');
        const message = `服务返回异常：${response.status} ${text}`;
        handlers.onError?.(message, String(response.status));
        throw new Error(message);
      }
      retries = 0;
    },

    onmessage(message) {
      if (message.id) {
        headers['Last-Event-ID'] = message.id;
      }
      if (!message.event || !message.data) return;
      if (message.event === 'error') {
        const parsed = JSON.parse(message.data) as Record<string, unknown>;
        handlers.onEvent({
          type: 'error',
          code: String(parsed.code ?? 'UNKNOWN'),
          message: String(parsed.message ?? '调研过程出现异常'),
          trace_id: String(parsed.trace_id ?? ''),
        } as ResearchEvent);
        return;
      }
      const parsed = JSON.parse(message.data) as Record<string, unknown>;
      const eventId = Number(message.id);
      handlers.onEvent(
        { type: message.event, ...parsed } as ResearchEvent,
        Number.isFinite(eventId) ? eventId : undefined,
      );
    },

    onerror(error) {
      if (controller.signal.aborted) {
        throw error;
      }
      const message = error instanceof Error ? error.message : '连接异常';
      if (fatal || retries >= MAX_RETRIES) {
        handlers.onError?.(message, fatal ? 'FATAL' : 'RETRY_EXHAUSTED');
        throw error;
      }
      retries += 1;
    },

    onclose() {
      handlers.onClose?.();
    },
  }).catch((error: unknown) => {
    if (!controller.signal.aborted) {
      console.error('[sse]', error);
    }
  });

  return controller;
}
