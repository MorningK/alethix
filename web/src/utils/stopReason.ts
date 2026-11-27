import { PAPER_COLORS } from '@/theme/paperTheme';
import type { Confidence, StopReason } from '@/types/ask';

export interface StopReasonMeta {
  label: string;
  description: string;
  tone: 'success' | 'info' | 'warning' | 'error';
}

/** stop_reason 到界面文案的统一映射（FE-CHAT-4）。 */
export const STOP_REASON_META: Record<StopReason, StopReasonMeta> = {
  sufficient: {
    label: '证据充分',
    description: '本次调研已基于足够证据形成结论，可逐条核对下方引用。',
    tone: 'success',
  },
  max_iterations_reached: {
    label: '已达轮次上限',
    description: '调研已达到设定轮次上限，结论可能不完整，建议缩小问题范围后重试。',
    tone: 'warning',
  },
  no_new_queries: {
    label: '无新增检索方向',
    description: '已有检索方向均已覆盖，当前结论基于已收集到的证据。',
    tone: 'info',
  },
  no_new_evidence: {
    label: '无新增有效证据',
    description: '继续检索未获得新的有效信息，结论基于现有证据。',
    tone: 'info',
  },
  low_relevance: {
    label: '未找到足够证据',
    description: '所选文档中未找到足够相关的证据，答案仅列出最相关内容供判断。',
    tone: 'warning',
  },
  budget_exceeded: {
    label: '检索预算受限',
    description: '因检索规模或耗时限制提前收尾，结论可能不完整。',
    tone: 'warning',
  },
  internal_error: {
    label: '执行出现异常',
    description: '调研过程中发生异常，请稍后重试；当前结论仅供参考。',
    tone: 'error',
  },
};

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

export const CONFIDENCE_COLOR: Record<Confidence, string> = {
  high: PAPER_COLORS.success,
  medium: PAPER_COLORS.primary,
  low: PAPER_COLORS.warning,
};

const UNKNOWN_STOP_REASON_META: StopReasonMeta = {
  label: '终止原因未记录',
  description: '该历史回答未携带终止原因，请结合答案与引用内容自行核对。',
  tone: 'info',
};

export function stopReasonMeta(reason: StopReason | null | undefined): StopReasonMeta {
  if (!reason) return UNKNOWN_STOP_REASON_META;
  return STOP_REASON_META[reason];
}
