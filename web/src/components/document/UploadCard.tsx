import { App, Card, Typography, Upload } from 'antd';
import { useMutation } from '@tanstack/react-query';
import { CloudUpload } from 'lucide-react';
import { uploadDocument } from '@/api/documents';
import type { ApiError } from '@/api/http';
import type { UploadDocumentResponse } from '@/types/document';
import { toUserMessage } from '@/utils/errorMessages';

const ALLOWED = ['pdf', 'md', 'txt'];
const MAX_BYTES = 50 * 1024 * 1024;

interface UploadCardProps {
  onUploaded: (result: UploadDocumentResponse) => void;
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const { message } = App.useApp();

  const upload = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: (result: UploadDocumentResponse) => {
      if (result.deduplicated) {
        message.info('该文件已上传过，已复用原记录');
      } else {
        message.success('上传成功，已加入处理队列');
      }
      onUploaded(result);
    },
    onError: (error) => {
      console.error('[upload]', error);
      const apiError = error as ApiError;
      message.error(toUserMessage(apiError.code, apiError.message));
    },
  });

  const beforeUpload = (file: File) => {
    const ext = file.name.toLowerCase().split('.').pop() ?? '';
    if (!ALLOWED.includes(ext)) {
      message.error('仅支持 PDF、Markdown（.md）和 TXT 文档');
      return Upload.LIST_IGNORE;
    }
    if (file.size > MAX_BYTES) {
      message.error('单个文件不能超过 50 MB');
      return Upload.LIST_IGNORE;
    }
    return true;
  };

  return (
    <Card className="paper-card paper-upload-card" styles={{ body: { padding: 0 } }}>
      <Upload.Dragger
        multiple
        accept=".pdf,.md,.txt"
        showUploadList={false}
        disabled={upload.isPending}
        beforeUpload={beforeUpload}
        customRequest={({ file, onSuccess, onError }) => {
          upload.mutate(file as File, {
            onSuccess: (result) => onSuccess?.(result),
            onError: (error) => onError?.(error as Error),
          });
        }}
        className="paper-upload-zone rounded-lg py-8"
      >
        <div className="flex flex-col items-center gap-3">
          <div className="paper-upload-icon flex size-12 items-center justify-center">
            <CloudUpload size={24} strokeWidth={1.8} />
          </div>
          <div className="flex flex-col gap-1">
            <Typography.Text strong className="text-ink text-base">
              拖拽文件到此处上传，或点击选择
            </Typography.Text>
            <Typography.Text type="secondary">
              支持 PDF / Markdown / TXT，单个文件不超过 50 MB
            </Typography.Text>
          </div>
        </div>
      </Upload.Dragger>
      <div className="paper-upload-footer border-t px-5 py-3 text-xs">
        上传后自动解析、切片并向量化；处理中的文档会在下方实时追踪状态。
      </div>
    </Card>
  );
}
