import { useCallback, useMemo, useRef, useState } from 'react';
import { App } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { deleteDocument, listDocuments } from '@/api/documents';
import type { ApiError } from '@/api/http';
import { createSession } from '@/api/sessions';
import { useAppStore } from '@/store/useAppStore';
import type {
  DocumentBrief,
  DocumentStatus,
  DocumentStatusResponse,
  UploadDocumentResponse,
} from '@/types/document';
import { toUserMessage } from '@/utils/errorMessages';
import { useDocumentPolling } from './useDocumentPolling';

const TERMINAL: DocumentStatus[] = ['ready', 'failed'];
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
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDocs, setPendingDocs] = useState<DocumentBrief[]>([]);
  const terminalSeen = useRef<Record<string, boolean>>({});

  const selectedDocIds = useAppStore((state) => state.selectedDocIds);
  const setSelectedDocIds = useAppStore((state) => state.setSelectedDocIds);
  const setCurrentSession = useAppStore((state) => state.setCurrentSession);
  const removeDocId = useAppStore((state) => state.removeDocId);

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

  const listError = useMemo(
    () => (documentsQuery.error ? reportError(documentsQuery.error, 'documents') : null),
    [documentsQuery.error],
  );
  const error = mutationError ?? listError;

  const handlePolledStatus = useCallback(
    (documentId: string, status: DocumentStatusResponse) => {
      if (TERMINAL.includes(status.status) && !terminalSeen.current[documentId]) {
        terminalSeen.current[documentId] = true;
        void queryClient.invalidateQueries({ queryKey: ['documents'] });
      }
    },
    [queryClient],
  );

  const mergedDocs = useMemo(() => {
    const merged = new Map<string, DocumentBrief>();
    pendingDocs.forEach((doc) => merged.set(doc.document_id, doc));
    documents.forEach((doc) => merged.set(doc.document_id, doc));
    return Array.from(merged.values());
  }, [pendingDocs, documents]);

  // 非 ready 文档都追踪一次：非终态持续轮询，failed 仅拉取一次错误详情。
  const trackedDocs = useMemo(
    () => mergedDocs.filter((doc) => doc.status !== 'ready'),
    [mergedDocs],
  );
  const trackedIds = useMemo(() => trackedDocs.map((doc) => doc.document_id), [trackedDocs]);

  const polls = useDocumentPolling(trackedIds, 2000, handlePolledStatus);

  const statusById = useMemo(() => {
    const result: Record<string, DocumentStatusResponse | undefined> = {};
    trackedDocs.forEach((doc, index) => {
      result[doc.document_id] = polls[index]?.data;
    });
    return result;
  }, [trackedDocs, polls]);

  // 轮询确认终态后，即使该文档被筛选条件排除，也不再显示为处理中。
  const processingDocs = useMemo(
    () =>
      mergedDocs.filter((doc) => {
        const effectiveStatus = statusById[doc.document_id]?.status ?? doc.status;
        return !TERMINAL.includes(effectiveStatus);
      }),
    [mergedDocs, statusById],
  );

  const handleUploaded = useCallback(
    (result: UploadDocumentResponse) => {
      setMutationError(null);
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
    onSuccess: (result, documentId) => {
      removeDocId(documentId);
      message.success(result.message || '删除请求已提交');
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['documents'] });
      }, 1000);
    },
    onError: (err) => {
      const text = reportError(err, 'delete');
      setMutationError(text);
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
      setCurrentSession(session);
      setSelectedDocIds(selectedDocIds);
      message.success('会话已创建，已带入所选文档范围');
      navigate(`/chat/${session.session_id}`);
    },
    onError: (err) => {
      const text = reportError(err, 'session');
      setMutationError(text);
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
    selectedIds: selectedDocIds,
    deletingId,
    error,
    processingDocs,
    statusById,
    asking: askMutation.isPending,
    onUploaded: handleUploaded,
    onStatusFilterChange: handleStatusFilterChange,
    onPageChange: handlePageChange,
    onSelectedIdsChange: setSelectedDocIds,
    onDelete: (documentId: string) => {
      setDeletingId(documentId);
      deleteMutation.mutate(documentId);
    },
    onAsk: () => askMutation.mutate(selectedDocIds),
    onRetry: () => {
      void documentsQuery.refetch();
    },
    clearError: () => setMutationError(null),
  };
}
