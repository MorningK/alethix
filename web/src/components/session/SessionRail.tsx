import { Button, Empty, Typography } from 'antd';
import { MessageSquareText, Plus } from 'lucide-react';
import { useCreateSession } from '@/hooks/useCreateSession';

interface CurrentSession {
  session_id: string;
  title?: string | null;
  default_document_ids?: string[];
  created_at?: string;
}

interface SessionRailProps {
  session: CurrentSession | null;
  className?: string;
}

/** 会话侧栏：只展示当前会话与新建入口，历史列表受现有 API 限制暂不提供。 */
export function SessionRail({ session, className = '' }: SessionRailProps) {
  const createSession = useCreateSession();

  return (
    <aside className={`paper-session-rail flex flex-col ${className}`} aria-label="会话信息">
      <div className="border-paper-line flex items-center justify-between border-b px-3 py-3">
        <Typography.Text strong className="text-ink">
          调研会话
        </Typography.Text>
        <Button
          type="primary"
          size="small"
          icon={<Plus size={14} />}
          loading={createSession.isPending}
          onClick={() => createSession.mutate()}
        >
          新建
        </Button>
      </div>

      <div className="flex flex-col gap-2 p-2">
        {session ? (
          <div className="paper-session-item is-active flex items-start gap-2">
            <MessageSquareText className="text-brand mt-0.5 size-4 shrink-0" />
            <div className="min-w-0">
              <Typography.Text strong className="block truncate text-sm">
                {session.title || '未命名会话'}
              </Typography.Text>
              <Typography.Text type="secondary" className="block text-xs">
                {session.default_document_ids?.length ?? 0} 篇文档 ·{' '}
                {session.session_id.slice(0, 8)}
              </Typography.Text>
            </div>
          </div>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="尚未选择会话"
            className="paper-empty py-6"
          />
        )}
      </div>

      <div className="border-paper-line text-ink-muted mt-auto border-t px-3 py-3 text-xs leading-5">
        会话范围保存在当前浏览器中；历史会话列表待后端接口支持后接入。
      </div>
    </aside>
  );
}
