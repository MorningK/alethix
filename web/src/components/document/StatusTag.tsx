import { Tag } from 'antd';
import type { DocumentStatus } from '@/types/document';

const STATUS_META: Record<DocumentStatus, { color: string; label: string }> = {
  uploaded: { color: 'default', label: '已上传' },
  parsing: { color: '#2563EB', label: '解析中' },
  chunking: { color: '#2563EB', label: '切片中' },
  embedding: { color: '#2563EB', label: '向量化中' },
  ready: { color: '#00B42A', label: '就绪' },
  failed: { color: '#F53F3F', label: '失败' },
};

export function StatusTag({ status }: { status: DocumentStatus }) {
  const meta = STATUS_META[status] ?? { color: 'default', label: status };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}
