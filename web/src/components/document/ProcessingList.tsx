import { Alert, Card, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import { LoaderCircle } from 'lucide-react';
import { StatusTag } from './StatusTag';
import type { DocumentBrief, DocumentStatusResponse } from '@/types/document';
import { formatTime } from '@/utils/format';

interface ProcessingListProps {
  documents: DocumentBrief[];
  statusById: Record<string, DocumentStatusResponse | undefined>;
}

export function ProcessingList({ documents, statusById }: ProcessingListProps) {
  if (documents.length === 0) return null;

  return (
    <Card
      title={
        <div className="flex items-center gap-2">
          <span>处理中</span>
          <Tag color="processing">{documents.length}</Tag>
        </div>
      }
      className="shadow-sm"
    >
      <div className="flex flex-col gap-3">
        {documents.map((doc) => {
          const status = statusById[doc.document_id]?.status ?? doc.status;
          const elapsedMinutes = dayjs().diff(dayjs(doc.created_at), 'minute');
          const timedOut = elapsedMinutes >= 10;
          return (
            <div
              key={doc.document_id}
              className="bg-canvas flex flex-col gap-2 rounded-lg px-4 py-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <LoaderCircle className="text-brand size-4 shrink-0 animate-spin" />
                  <Typography.Text strong className="text-ink truncate">
                    {doc.filename}
                  </Typography.Text>
                  <StatusTag status={status} />
                </div>
                <Typography.Text type="secondary" className="text-xs">
                  开始于 {formatTime(doc.created_at)}
                </Typography.Text>
              </div>
              {timedOut && (
                <Alert
                  type="warning"
                  showIcon
                  message="处理时间已超过 10 分钟，请稍后刷新状态或重新上传该文件"
                />
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
