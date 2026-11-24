import { useCallback, useMemo, useState } from 'react';
import { App } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { deleteDocument, listDocuments } from '@/api/documents';
import type { ApiError } from '@/api/http';
import { createSession } from '@/api/sessions';
import { useAppStore } from '@/store/useAppStore';
import type {
  DocumentBrief,
  DocumentStatusResponse,
  UploadDocumentResponse,
} from '@/types/document';
import { toUserMessage } from '@/utils/errorMessages';
import { useDocumentPolling } from './useDocumentPolling';

const TERMINAL = ['ready', 'failed'];
const EMPTY_DOCUMENTS: DocumentBrief[] = [];

function reportError(error: unknown, scope: string): string {
  console.error(`[${scope}]`, error);
  const apiError = error as ApiError;
  return toUserMessage(apiError.code, apiError.message);
}

export function useDocumentManager() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [statusFilter, setStatusFilter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDocs, setPendingDocs] = useState<DocumentBrief[]>([]);

  const selectedDocIds = useAppStore((state) => state.selectedDocIds);
  const setSelectedDocIds = useAppStore((state) => state.setSelectedDocIds);
  const setCurrentSessionId = useAppStore((state) => state.setCurrentSessionId);

  const documentsQuery = useQuery({
    queryKey: ['documents', page, pageSize, statusFilter],
    queryFn: () =>
      listDocuments({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      }),
  });

  const documents = documentsQuery.data?.items ?? EMPTY_DOCUMENTS;
  const total = documentsQuery.data?.total ?? 0;

  const processingDocs = useMemo(() => {
    const merged = new Map<string, DocumentBrief>();
    pendingDocs.forEach((doc) => merged.set(doc.document_id, doc));
    documents.forEach((doc) => merged.set(doc.document_id, doc));
    return Array.from(merged.values()).filter((doc) => !TERMINAL.includes(doc.status));
  }, [pendingDocs, documents]);

  // 失败文档为终态，不再轮询状态变化；仅在列表刷新时拉取一次错误详情。
  const trackedDocs = useMemo(() => {
    const tracked = new Map(processingDocs.map((doc) => [doc.document_id, doc]));
    documents
      .filter((doc) => doc.status === 'failed')
      .forEach((doc) => tracked.set(doc.document_id, doc));
    return Array.from(tracked.values());
  }, [processingDocs, documents]);

  const polls = useDocumentPolling(trackedDocs.map((doc) => doc.document_id));

  const statusById = useMemo(() => {
    const result: Record<string, DocumentStatusResponse | undefined> = {};
    trackedDocs.forEach((doc, index) => {
      result[doc.document_id] = polls[index]?.data;
    });
    return result;
  }, [trackedDocs, polls]);

  const selectedIds = useMemo(
    () =>
      selectedDocIds.filter((id) =>
        documents.some((doc) => doc.document_id === id && doc.status === 'ready'),
      ),
    [selectedDocIds, documents],
  );

  const handleUploaded = useCallback(
    (result: UploadDocumentResponse) => {
      setError(null);
      if (!result.deduplicated) {
        setPendingDocs((prev) => [
          ...prev,
          {
            document_id: result.document_id,
            filename: result.filename,
            status: result.status,
            chunk_count: null,
            page_count: null,
          },
        ]);
      }
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    [queryClient],
  );

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: (result) => {
      message.success(result.message || '删除请求已提交');
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['documents'] });
      }, 1000);
    },
    onError: (err) => {
      const text = reportError(err, 'delete');
      setError(text);
      message.error(text);
    },
    onSettled: () => setDeletingId(null),
  });

  const askMutation = useMutation({
    mutationFn: (ids: string[]) =>
      createSession({
        title: ids.length ? `基于 ${ids.length} 篇文档的问答` : '全部文档问答',
        default_document_ids: ids,
      }),
    onSuccess: (session) => {
      setCurrentSessionId(session.session_id);
      setSelectedDocIds(selectedIds);
      message.success('会话已创建，已带入所选文档范围');
      navigate(`/chat/${session.session_id}`);
    },
    onError: (err) => {
      const text = reportError(err, 'session');
      setError(text);
      message.error(text);
    },
  });

  const handleStatusFilterChange = useCallback((value: string) => {
    setStatusFilter(value);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((nextPage: number, nextPageSize: number) => {
    setPage(nextPage);
    setPageSize(nextPageSize);
  }, []);

  return {
    documents,
    total,
    loading: documentsQuery.isLoading,
    page,
    pageSize,
    statusFilter,
    selectedIds,
    deletingId,
    error,
    processingDocs,
    statusById,
    uploading: false,
    asking: askMutation.isPending,
    onUploaded: handleUploaded,
    onError: (value: string) => setError(value),
    onStatusFilterChange: handleStatusFilterChange,
    onPageChange: handlePageChange,
    onSelectedIdsChange: setSelectedDocIds,
    onDelete: (documentId: string) => {
      setDeletingId(documentId);
      deleteMutation.mutate(documentId);
    },
    onAsk: () => askMutation.mutate(selectedIds),
    clearError: () => setError(null),
  };
}
