import { Collapse, Empty, Typography } from 'antd';
import { XMarkdown } from '@ant-design/x-markdown';
import type { Citation } from '@/types/document';

interface CitationListProps {
  citations: Citation[];
  defaultOpen?: boolean;
}

/** 引用区：元数据保持纯文本，原文摘录用 XMarkdown 紧凑渲染。 */
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
                  <XMarkdown
                    content={citation.quote}
                    className="citation-markdown text-ink-muted border-brand-light border-l-2 pl-3 text-xs"
                    openLinksInNewTab
                    escapeRawHtml
                  />
                </div>
              ))}
            </div>
          ),
        },
      ]}
    />
  );
}
