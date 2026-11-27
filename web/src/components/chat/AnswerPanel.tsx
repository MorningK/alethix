import { Alert, Card, Tag, Typography } from 'antd';
import type { FinalAnswerEvent } from '@/types/sse';
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL, stopReasonMeta } from '@/utils/stopReason';
import { CitationList } from './CitationList';

interface AnswerPanelProps {
  answer: FinalAnswerEvent;
}

/** 最终答案面板：答案、置信度、终止原因提示与引用（FE-CHAT-4 / FE-CHAT-5）。 */
export function AnswerPanel({ answer }: AnswerPanelProps) {
  const meta = stopReasonMeta(answer.stop_reason);
  const seconds = Math.max(1, Math.round(answer.duration_ms / 1000));

  return (
    <Card
      title="调研结论"
      className="border-slate-100 shadow-sm"
      styles={{ body: { padding: 20, display: 'flex', flexDirection: 'column', gap: 16 } }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Tag color={CONFIDENCE_COLOR[answer.confidence]}>
          置信度：{CONFIDENCE_LABEL[answer.confidence]}
        </Tag>
        <Tag>{meta.label}</Tag>
        <Typography.Text type="secondary" className="text-xs">
          共 {answer.iteration_count} 轮 · 耗时约 {seconds} 秒 · 消耗 {answer.token_used} tokens
        </Typography.Text>
      </div>

      <Alert type={meta.tone} showIcon message={meta.label} description={meta.description} />

      <Typography.Paragraph className="text-ink mb-0 leading-7 whitespace-pre-wrap">
        {answer.answer}
      </Typography.Paragraph>

      <CitationList citations={answer.citations} />
    </Card>
  );
}
