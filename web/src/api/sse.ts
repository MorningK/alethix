import { fetchEventSource } from '@microsoft/fetch-event-source';
import type { AskRequest } from '@/types/ask';
import type { ResearchEvent } from '@/types/sse';

const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const devUserId = import.meta.env.VITE_USER_ID ?? '';

export interface StreamHandlers {
  onEvent: (event: ResearchEvent) => void;
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

  fetchEventSource(`${baseURL}/ask/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(devUserId ? { 'X-User-Id': devUserId } : {}),
    },
    body: JSON.stringify(payload),
    signal: controller.signal,

    async onopen(response) {
      if (!response.ok) {
        const text = await response.text().catch(() => '');
        handlers.onError?.(`服务返回异常：${response.status} ${text}`, String(response.status));
      }
    },

    onmessage(message) {
      // 心跳是 `: ping` 注释行，fetch-event-source 已过滤；此处再兜一层
      if (!message.event || !message.data) return;

      const parsed = JSON.parse(message.data) as Record<string, unknown>;
      handlers.onEvent({ type: message.event, ...parsed } as ResearchEvent);
    },

    onerror(error) {
      // 返回给库的 error 会被抛出；这里转为可读提示并中止重试
      handlers.onError?.(error instanceof Error ? error.message : '连接异常');
      throw error;
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
