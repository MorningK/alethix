import { http } from './http';
import type {
  DocumentBrief,
  DocumentStatusResponse,
  UploadDocumentResponse,
} from '@/types/document';
import type { Paginated } from '@/types/session';

export interface ListDocumentsParams {
  status?: string;
  page?: number;
  page_size?: number;
}

/** API-4 文档列表 */
export async function listDocuments(params: ListDocumentsParams = {}) {
  const { data } = await http.get<Paginated<DocumentBrief>>('/documents', { params });
  return data;
}

/** API-2 上传文档 */
export async function uploadDocument(file: File, sessionId?: string) {
  const form = new FormData();
  form.append('file', file);
  if (sessionId) form.append('session_id', sessionId);
  const { data } = await http.post<UploadDocumentResponse>('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

/** API-3 查询处理状态 */
export async function getDocumentStatus(documentId: string) {
  const { data } = await http.get<DocumentStatusResponse>(`/documents/${documentId}/status`);
  return data;
}

/** API-5 删除文档 */
export async function deleteDocument(documentId: string) {
  await http.delete(`/documents/${documentId}`);
}
