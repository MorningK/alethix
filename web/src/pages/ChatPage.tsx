import { Alert, Card, Empty, Typography } from 'antd';
import { useParams } from 'react-router-dom';

/**
 * 问答调研页（占位骨架）。
 * 功能实现见 prd/07-frontend.md §4.4，对应前端里程碑 F3 / F4。
 * 调研时间线是核心差异化体验：逐轮展示「查询 → 命中 → 判定」。
 */
export function ChatPage() {
  const { sessionId } = useParams();

  return (
    <div className="flex flex-col gap-4">
      <Typography.Title level={4} className="mb-0!">
        智能问答
      </Typography.Title>

      {!sessionId && <Alert type="info" showIcon message="未指定会话，将使用最近会话或新建会话" />}

      <Card title="调研过程" className="shadow-none">
        <Empty description="调研时间线待 F3 实现：按轮次展示查询、命中与判定" />
      </Card>

      <Card title="答案" className="shadow-none">
        <Empty description="答案、引用与置信度待 F3 实现" />
      </Card>
    </div>
  );
}
