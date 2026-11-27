import { Alert, Button, Popconfirm, Select, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { FileText } from 'lucide-react';
import { StatusTag } from './StatusTag';
import type { DocumentBrief, DocumentStatus, DocumentStatusResponse } from '@/types/document';
import { formatFileSize, formatTime } from '@/utils/format';

function FailureDetail({ code, message }: { code: string; message: string }) {
  return <Alert type="error" showIcon title={`${code}：${message}`} className="my-2" />;
}

function renderExpandedRow(
  record: DocumentBrief,
  statusById: Record<string, DocumentStatusResponse | undefined>,
) {
  const error = statusById[record.document_id]?.error;
  return error ? <FailureDetail code={error.code} message={error.message} /> : null;
}

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'uploaded', label: '已上传' },
  { value: 'parsing', label: '解析中' },
  { value: 'chunking', label: '切片中' },
  { value: 'embedding', label: '向量化中' },
  { value: 'ready', label: '就绪' },
  { value: 'failed', label: '失败' },
];

interface DocumentTableProps {
  documents: DocumentBrief[];
  loading: boolean;
  total: number;
  page: number;
  pageSize: number;
  statusFilter: string;
  selectedIds: string[];
  deletingId: string | null;
  statusById: Record<string, DocumentStatusResponse | undefined>;
  onStatusFilterChange: (value: string) => void;
  onPageChange: (page: number, pageSize: number) => void;
  onSelectedIdsChange: (ids: string[]) => void;
  onDelete: (documentId: string) => void;
}

export function DocumentTable({
  documents,
  loading,
  total,
  page,
  pageSize,
  statusFilter,
  selectedIds,
  deletingId,
  statusById,
  onStatusFilterChange,
  onPageChange,
  onSelectedIdsChange,
  onDelete,
}: DocumentTableProps) {
  const columns: TableColumnsType<DocumentBrief> = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      render: (_, record) => (
        <div className="flex min-w-0 items-center gap-2">
          <FileText className="text-brand size-4 shrink-0" />
          <Typography.Text strong className="truncate">
            {record.filename}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '格式',
      dataIndex: 'source_format',
      key: 'source_format',
      width: 90,
      render: (value?: string) => <Tag>{value?.toUpperCase() ?? '-'}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size_bytes',
      key: 'file_size_bytes',
      width: 110,
      render: (value?: number) => formatFileSize(value),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (value: DocumentStatus) => <StatusTag status={value} />,
    },
    {
      title: '切片',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
      render: (value: number | null) => (value === null ? '-' : value),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (value?: string) => formatTime(value),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Popconfirm
          title="删除文档"
          description="删除后将从检索范围移除，确定继续吗？"
          okText="确定删除"
          cancelText="取消"
          onConfirm={() => onDelete(record.document_id)}
        >
          <Button
            type="link"
            danger
            size="small"
            loading={deletingId === record.document_id}
            disabled={record.status !== 'ready' && record.status !== 'failed'}
          >
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <Typography.Text strong className="text-ink text-base">
          文档列表
        </Typography.Text>
        <Select
          value={statusFilter}
          options={STATUS_OPTIONS}
          onChange={onStatusFilterChange}
          className="w-36"
          aria-label="文档状态筛选"
        />
      </div>
      <Table<DocumentBrief>
        rowKey="document_id"
        columns={columns}
        dataSource={documents}
        loading={loading}
        size="middle"
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          onChange: onPageChange,
        }}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys) => onSelectedIdsChange(keys.map(String)),
          getCheckboxProps: (record) => ({
            disabled: record.status !== 'ready' || deletingId === record.document_id,
          }),
        }}
        expandable={{
          rowExpandable: (record) =>
            record.status === 'failed' && Boolean(statusById[record.document_id]?.error),
          expandedRowRender: (record) => renderExpandedRow(record, statusById),
        }}
      />
    </div>
  );
}
