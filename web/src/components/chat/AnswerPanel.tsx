import { Alert, Tag, Typography } from 'antd';
import { XMarkdown } from '@ant-design/x-markdown';
import type { ChatAnswer } from '@/utils/chatAdapters';
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL, stopReasonMeta } from '@/utils/stopReason';

interface AnswerPanelProps {
  answer: ChatAnswer;
}

/** 最终答案内容：Markdown 正文 + 置信度与终止原因。 */
export function AnswerPanel({ answer }: AnswerPanelProps) {
  const meta = stopReasonMeta(answer.stop_reason);
  const seconds = Math.max(1, Math.round(answer.duration_ms / 1000));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tag color={CONFIDENCE_COLOR[answer.confidence]}>
          置信度：{CONFIDENCE_LABEL[answer.confidence]}
        </Tag>
        <Tag>{meta.label}</Tag>
        <Typography.Text type="secondary" className="text-xs">
          共 {answer.iteration_count || 1} 轮 · 耗时约 {seconds} 秒 · 消耗 {answer.token_used}{' '}
          tokens
        </Typography.Text>
      </div>

      <Alert type={meta.tone} showIcon title={meta.label} description={meta.description} />

      <XMarkdown
        content={answer.answer}
        className="x-markdown-light text-ink text-sm leading-7"
        openLinksInNewTab
        escapeRawHtml
      />
    </div>
  );
}
