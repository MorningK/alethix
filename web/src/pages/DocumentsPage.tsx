import { Card, Empty, Table, Tag, Typography } from 'antd';
import type { DocumentStatus } from '@/types/document';

const STATUS_COLOR: Record<DocumentStatus, string> = {
  uploaded: 'default',
  parsing: 'blue',
  chunking: 'blue',
  embedding: 'blue',
  ready: 'green',
  failed: 'red',
};

/**
 * 文档管理页（占位骨架）。
 * 功能实现见 prd/07-frontend.md §4.3，对应前端里程碑 F2。
 */
export function DocumentsPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <Typography.Title level={4} className="mb-1!">
          文档管理
        </Typography.Title>
        <Typography.Text type="secondary">
          上传 PDF / Markdown / TXT，单个文件不超过 50 MB
        </Typography.Text>
      </div>

      <Card title="上传" className="shadow-none">
        <Typography.Text type="secondary">
          上传组件待 F2 实现（AntD Upload 拖拽上传 + 前端校验）
        </Typography.Text>
      </Card>

      <Card title="文档列表" className="shadow-none">
        <Table
          dataSource={[]}
          rowKey="document_id"
          locale={{ emptyText: <Empty description="暂无文档，请先上传" /> }}
          columns={[
            { title: '文件名', dataIndex: 'filename' },
            { title: '格式', dataIndex: 'source_format' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (status: DocumentStatus) => <Tag color={STATUS_COLOR[status]}>{status}</Tag>,
            },
            { title: '切片数', dataIndex: 'chunk_count' },
          ]}
          pagination={false}
        />
      </Card>
    </div>
  );
}
