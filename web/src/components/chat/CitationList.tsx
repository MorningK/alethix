import { Collapse, Empty, Typography } from 'antd';
import type { Citation } from '@/types/document';

interface CitationListProps {
  citations: Citation[];
  defaultOpen?: boolean;
}

/** 引用区：默认折叠，展示文件名 / 页码 / 章节 / 原文摘录（FE-CHAT-5）。 */
export function CitationList({ citations, defaultOpen = false }: CitationListProps) {
  if (citations.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="本次答案未附带可核验的原文引用"
        className="py-4"
      />
    );
  }

  return (
    <Collapse
      ghost
      defaultActiveKey={defaultOpen ? ['citations'] : []}
      items={[
        {
          key: 'citations',
          label: <Typography.Text strong>引用来源（{citations.length}）</Typography.Text>,
          children: (
            <div className="flex flex-col gap-3">
              {citations.map((citation, index) => (
                <div
                  key={citation.chunk_id}
                  className="flex flex-col gap-1 rounded-md border border-slate-100 bg-slate-50 px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Typography.Text className="text-brand text-xs font-medium">
                      [{index + 1}] {citation.filename}
                    </Typography.Text>
                    {citation.page !== null && (
                      <Typography.Text type="secondary" className="text-xs">
                        第 {citation.page} 页
                      </Typography.Text>
                    )}
                    {citation.section && (
                      <Typography.Text type="secondary" className="text-xs">
                        {citation.section}
                      </Typography.Text>
                    )}
                  </div>
                  <Typography.Text className="border-brand-light text-ink-muted border-l-2 pl-3 text-xs leading-relaxed">
                    {citation.quote}
                  </Typography.Text>
                </div>
              ))}
            </div>
          ),
        },
      ]}
    />
  );
}
