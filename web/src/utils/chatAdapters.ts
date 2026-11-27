import type { ReactNode } from 'react';
import type { Citation } from '@/types/document';
import type { Confidence, StopReason } from '@/types/ask';
import type { Message } from '@/types/session';
import type { TimelineNode } from '@/types/sse';
import { stopReasonMeta } from './stopReason';

export type ChatMessageStatus = 'local' | 'loading' | 'updating' | 'success' | 'error' | 'abort';
export type ResearchStatus = 'loading' | 'success' | 'error' | 'abort';

export interface ChatAnswer {
  agent_run_id: string;
  answer: string;
  confidence: Confidence;
  stop_reason: StopReason | null;
  iteration_count: number;
  duration_ms: number;
  token_used: number;
  citations: Citation[];
}

export interface ChatBubbleContent {
  text: string;
  answer?: ChatAnswer;
}

export interface ChatBubbleItem {
  key: string;
  role: 'user' | 'ai';
  placement: 'start' | 'end';
  status: ChatMessageStatus;
  content: ChatBubbleContent;
  loading?: boolean;
  footer?: ReactNode;
}

export interface ResearchChainItem {
  key: string;
  title: string;
  description: ReactNode;
  content: ReactNode;
  status: ResearchStatus;
  collapsible: boolean;
  blink?: boolean;
}

export interface PromptItem {
  key: string;
  label: string;
  description: string;
}

export const RECOMMENDED_PROMPTS: PromptItem[] = [
  {
    key: 'risk',
    label: '梳理主要风险',
    description: '结合所选文档，说明项目面临的主要风险及原文依据',
  },
  {
    key: 'compare',
    label: '比较多篇文档',
    description: '比较所选文档对同一问题的说法是否一致，并指出差异',
  },
  {
    key: 'evidence',
    label: '核实关键结论',
    description: '查找文档中支撑核心结论的数据、定义与限制条件',
  },
];

function messageToAnswer(message: Message): ChatAnswer | undefined {
  if (message.role !== 'assistant') return undefined;
  if (!message.citations && !message.confidence) return undefined;
  return {
    agent_run_id: message.agent_run_id ?? '',
    answer: message.content,
    confidence: message.confidence ?? 'medium',
    stop_reason: null,
    iteration_count: 0,
    duration_ms: 0,
    token_used: 0,
    citations: message.citations ?? [],
  };
}

export function toBubbleItems(params: {
  history: Message[];
  currentQuestion: string | null;
  running: boolean;
  finalAnswer: ChatAnswer | null;
  error: string | null;
  aborted: boolean;
}): ChatBubbleItem[] {
  const { history, currentQuestion, running, finalAnswer, error, aborted } = params;
  const items: ChatBubbleItem[] = history.map((message) => ({
    key: `history-${message.message_id}`,
    role: message.role === 'user' ? 'user' : 'ai',
    placement: message.role === 'user' ? 'end' : 'start',
    status: 'success',
    content: { text: message.content, answer: messageToAnswer(message) },
  }));

  if (currentQuestion) {
    items.push({
      key: `current-question-${items.length}`,
      role: 'user',
      placement: 'end',
      status: 'success',
      content: { text: currentQuestion },
    });
  }

  if (finalAnswer) {
    items.push({
      key: `current-answer-${finalAnswer.agent_run_id}`,
      role: 'ai',
      placement: 'start',
      status: 'success',
      content: { text: finalAnswer.answer, answer: finalAnswer },
    });
  } else if (error || aborted) {
    items.push({
      key: 'current-status',
      role: 'ai',
      placement: 'start',
      status: aborted ? 'abort' : 'error',
      content: { text: error ?? '调研已停止' },
    });
  } else if (running) {
    items.push({
      key: 'current-loading',
      role: 'ai',
      placement: 'start',
      status: 'loading',
      loading: true,
      content: { text: '' },
    });
  }

  return items;
}

export function toResearchChainItems(
  nodes: TimelineNode[],
  finalAnswer: ChatAnswer | null,
): ResearchChainItem[] {
  return nodes.map((node) => {
    const status: ResearchStatus = node.loading
      ? 'loading'
      : finalAnswer && node.decision === 'answer'
        ? stopReasonMeta(finalAnswer.stop_reason).tone === 'error'
          ? 'error'
          : 'success'
        : 'success';
    const metrics = [
      `召回 ${node.retrieved_chunk_count ?? 0} 条`,
      `新增 ${node.new_chunk_count ?? 0} 条`,
      `最高分 ${(node.max_score ?? 0).toFixed(2)}`,
    ].join(' · ');

    return {
      key: `iter-${node.iteration}`,
      title: `第 ${node.iteration} 轮检索`,
      description: node.queries.join('；'),
      content: [
        metrics,
        node.reason,
        node.missing_information ? `信息缺口：${node.missing_information}` : '',
      ]
        .filter(Boolean)
        .join('\n'),
      status,
      collapsible: true,
      blink: node.loading,
    };
  });
}
