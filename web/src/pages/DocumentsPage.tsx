import { Button, Card, Typography } from 'antd';
import { ArrowRight } from 'lucide-react';
import { ErrorAlert } from '@/components/common/ErrorAlert';
import { DocumentTable } from '@/components/document/DocumentTable';
import { ProcessingList } from '@/components/document/ProcessingList';
import { UploadCard } from '@/components/document/UploadCard';
import { useDocumentManager } from '@/hooks/useDocumentManager';

export function DocumentsPage() {
  const manager = useDocumentManager();

  return (
    <div className="flex flex-col gap-5">
      <div className="paper-page-header flex flex-col gap-1">
        <span className="paper-eyebrow">Knowledge Base</span>
        <Typography.Title level={4} className="paper-title text-ink mt-2 mb-0">
          文档管理
        </Typography.Title>
        <Typography.Text type="secondary">
          上传 PDF、Markdown 或 TXT，就绪后即可作为问答的可核验依据
        </Typography.Text>
      </div>

      <ErrorAlert
        message={manager.error}
        onClose={manager.clearError}
        onRetry={manager.retryable ? manager.onRetry : undefined}
      />
      <UploadCard onUploaded={manager.onUploaded} />
      <ProcessingList documents={manager.processingDocs} statusById={manager.statusById} />

      <Card className="paper-card">
        <DocumentTable
          documents={manager.documents}
          loading={manager.loading}
          total={manager.total}
          page={manager.page}
          pageSize={manager.pageSize}
          statusFilter={manager.statusFilter}
          selectedIds={manager.selectedIds}
          deletingId={manager.deletingId}
          statusById={manager.statusById}
          onStatusFilterChange={manager.onStatusFilterChange}
          onPageChange={manager.onPageChange}
          onSelectedIdsChange={manager.onSelectedIdsChange}
          onDelete={manager.onDelete}
        />

        <div className="paper-selection-bar mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <Typography.Text type="secondary">
            已选 {manager.selectedIds.length} 篇就绪文档；未选择时将在全部就绪文档中检索
          </Typography.Text>
          <Button
            type="primary"
            icon={<ArrowRight size={16} />}
            loading={manager.asking}
            onClick={manager.onAsk}
          >
            基于选中文档发起提问
          </Button>
        </div>
      </Card>
    </div>
  );
}
