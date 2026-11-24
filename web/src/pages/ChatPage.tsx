import { Alert, Card, Empty, Tag, Typography } from 'antd';
import { useParams } from 'react-router-dom';
import { useAppStore } from '@/store/useAppStore';

/** 问答调研页：F2 跳转后的会话与检索范围承接，问答 UI 属于 F3。 */
export function ChatPage() {
  const { sessionId } = useParams();
  const currentSessionId = useAppStore((state) => state.currentSessionId);
  const selectedDocIds = useAppStore((state) => state.selectedDocIds);
  const activeSessionId = sessionId ?? currentSessionId;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <Typography.Title level={4} className="text-ink mb-0">
          智能问答
        </Typography.Title>
        <Typography.Text type="secondary">
          会话与检索范围已就绪，可直接接入单次问答与调研时间线
        </Typography.Text>
      </div>

      {!activeSessionId && (
        <Alert type="info" showIcon message="尚未创建会话，请先在文档管理页选择文档并发起提问" />
      )}

      <Card title="会话信息" className="shadow-sm">
        {activeSessionId ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <Typography.Text type="secondary">会话 ID</Typography.Text>
              <Typography.Text code copyable>
                {activeSessionId}
              </Typography.Text>
            </div>
            <div className="flex flex-col gap-2">
              <Typography.Text type="secondary">
                检索范围（
                {selectedDocIds.length > 0 ? `${selectedDocIds.length} 篇文档` : '全部就绪文档'}）
              </Typography.Text>
              <div className="flex flex-wrap gap-2">
                {selectedDocIds.length > 0 ? (
                  selectedDocIds.map((id) => <Tag key={id}>{id.slice(0, 8)}…</Tag>)
                ) : (
                  <Tag color="blue">全部就绪文档</Tag>
                )}
              </div>
            </div>
          </div>
        ) : (
          <Empty description="暂无会话" />
        )}
      </Card>

      <Card title="调研过程" className="shadow-sm">
        <Typography.Text type="secondary">
          单次检索问答已可通过 API-6 调用；过程可视化与答案引用面板将在 F3 实现。
        </Typography.Text>
      </Card>
    </div>
  );
}
