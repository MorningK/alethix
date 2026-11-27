import { Avatar, Typography } from 'antd';
import { Bubble } from '@ant-design/x';
import type { ChatBubbleContent, ChatBubbleItem } from '@/utils/chatAdapters';
import { AnswerPanel } from './AnswerPanel';
import { CitationList } from './CitationList';

interface ChatMessageListProps {
  items: ChatBubbleItem[];
}

const roles = {
  user: {
    placement: 'end' as const,
    avatar: <Avatar className="bg-blue-600">你</Avatar>,
    variant: 'filled' as const,
    contentRender: (content: unknown) => {
      const item = content as ChatBubbleContent;
      return <Typography.Text className="whitespace-pre-wrap">{item?.text ?? ''}</Typography.Text>;
    },
  },
  ai: {
    placement: 'start' as const,
    avatar: <Avatar className="bg-indigo-600">AI</Avatar>,
    variant: 'outlined' as const,
    loadingRender: () => <Typography.Text type="secondary">智能体正在分析证据…</Typography.Text>,
    contentRender: (content: unknown) => {
      const item = content as ChatBubbleContent;
      if (item?.answer) return <AnswerPanel answer={item.answer} />;
      return <Typography.Text className="whitespace-pre-wrap">{item?.text ?? ''}</Typography.Text>;
    },
    footer: (content: unknown) => {
      const item = content as ChatBubbleContent;
      if (!item?.answer?.citations.length) return null;
      return <CitationList citations={item.answer.citations} />;
    },
  },
};

/** 对话气泡列表：合并历史消息与当前流式状态。 */
export function ChatMessageList({ items }: ChatMessageListProps) {
  return (
    <Bubble.List
      items={items as Parameters<typeof Bubble.List>[0]['items']}
      role={roles}
      autoScroll
      className="min-h-0 flex-1 overflow-auto px-4 py-5"
    />
  );
}
