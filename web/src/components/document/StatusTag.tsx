import { Tag } from 'antd';
import type { DocumentStatus } from '@/types/document';

const STATUS_LABEL: Record<DocumentStatus, string> = {
  uploaded: '已上传',
  parsing: '解析中',
  chunking: '切片中',
  embedding: '向量化中',
  ready: '就绪',
  failed: '失败',
};

/** 文档六态标签：颜色由纸感 CSS token 控制，文案与后端状态一一对应。 */
export function StatusTag({ status }: { status: DocumentStatus }) {
  return (
    <Tag className={`paper-status paper-status--${status}`}>{STATUS_LABEL[status] ?? status}</Tag>
  );
}
