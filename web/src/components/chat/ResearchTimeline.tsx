import { Spin, Tag, Timeline, Typography } from 'antd';
import type { TimelineNode } from '@/types/sse';

interface ResearchTimelineProps {
  nodes: TimelineNode[];
  running: boolean;
}

/** 调研时间线：逐轮展示查询、召回、判断与理由（FE-CHAT-3）。 */
export function ResearchTimeline({ nodes, running }: ResearchTimelineProps) {
  if (nodes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-white px-5 py-8 text-center">
        <Typography.Text type="secondary">
          {running
            ? '调研已启动，正在规划第一批检索查询…'
            : '发起提问后，每一轮的检索与判断会在这里实时呈现。'}
        </Typography.Text>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-100 bg-white px-5 py-4">
      <Timeline
        items={nodes.map((node) => ({
          color: node.loading ? '#3B82F6' : node.decision === 'answer' ? '#00B42A' : '#2563EB',
          children: (
            <div className="node-enter flex flex-col gap-2 pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <Typography.Text strong>第 {node.iteration} 轮</Typography.Text>
                {node.loading ? (
                  <Tag icon={<Spin size="small" />} color="processing">
                    调研中
                  </Tag>
                ) : (
                  <Tag color={node.decision === 'answer' ? 'success' : 'blue'}>
                    {node.decision === 'answer' ? '收尾作答' : '继续追查'}
                  </Tag>
                )}
                {node.retrieved_chunk_count !== undefined && (
                  <Typography.Text type="secondary" className="text-xs">
                    召回 {node.retrieved_chunk_count} 条 · 新增 {node.new_chunk_count ?? 0} 条 ·
                    最高分 {(node.max_score ?? 0).toFixed(2)}
                  </Typography.Text>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {node.queries.map((query) => (
                  <Tag key={query} bordered={false} color="default">
                    {query}
                  </Tag>
                ))}
              </div>
              {node.reason && (
                <Typography.Text type="secondary" className="text-xs leading-relaxed">
                  {node.reason}
                </Typography.Text>
              )}
              {node.missing_information && (
                <Typography.Text type="secondary" className="text-xs leading-relaxed">
                  信息缺口：{node.missing_information}
                </Typography.Text>
              )}
            </div>
          ),
        }))}
      />
    </div>
  );
}
