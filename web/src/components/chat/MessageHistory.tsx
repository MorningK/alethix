import { Alert, Card, Empty, Spin, Typography } from 'antd';
import { useSessionMessages } from '@/hooks/useSession';
import type { Message } from '@/types/session';
import { CitationList } from './CitationList';

interface MessageHistoryProps {
  sessionId: string | null;
}

/** 会话历史：按时间正序展示问答与引用，数据来自 API-8。 */
export function MessageHistory({ sessionId }: MessageHistoryProps) {
  const { data, isLoading, isError } = useSessionMessages(sessionId);

  if (!sessionId) {
    return (
      <Card title="会话历史" className="border-slate-100 shadow-sm">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="创建会话后可在同一会话内继续追问"
        />
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card title="会话历史" className="border-slate-100 shadow-sm">
        <div className="flex items-center justify-center py-8">
          <Spin tip="正在加载会话历史" />
        </div>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card title="会话历史" className="border-slate-100 shadow-sm">
        <Alert
          type="warning"
          showIcon
          message="会话历史暂不可用"
          description="新问答不受影响，可稍后重试。"
        />
      </Card>
    );
  }

  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <Card title="会话历史" className="border-slate-100 shadow-sm">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="还没有问答记录，先提出第一个问题吧"
        />
      </Card>
    );
  }

  return (
    <Card
      title="会话历史"
      className="border-slate-100 shadow-sm"
      styles={{ body: { padding: 16, display: 'flex', flexDirection: 'column', gap: 12 } }}
    >
      {items.map((message: Message) => (
        <div
          key={message.message_id}
          className={`flex flex-col gap-2 rounded-lg px-4 py-3 ${
            message.role === 'user' ? 'bg-blue-50' : 'bg-slate-50'
          }`}
        >
          <div className="flex items-center gap-2">
            <Typography.Text strong className="text-brand-dark text-xs">
              {message.role === 'user' ? '你' : '调研智能体'}
            </Typography.Text>
            <Typography.Text type="secondary" className="text-xs">
              {new Date(message.created_at).toLocaleString('zh-CN', { hour12: false })}
            </Typography.Text>
          </div>
          <Typography.Paragraph className="text-ink mb-0 leading-6 whitespace-pre-wrap">
            {message.content}
          </Typography.Paragraph>
          {message.role === 'assistant' && <CitationList citations={message.citations ?? []} />}
        </div>
      ))}
    </Card>
  );
}
