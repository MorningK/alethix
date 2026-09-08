/** 文档处理状态（README 状态枚举速查） */
export type DocumentStatus = 'uploaded' | 'parsing' | 'chunking' | 'embedding' | 'ready' | 'failed';

export type SourceFormat = 'pdf' | 'docx' | 'md' | 'txt' | 'html';

/** 文档摘要，对应 prd/05-api-spec.md §2.1 */
export interface DocumentBrief {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  source_format?: SourceFormat;
  file_size_bytes?: number;
  chunk_count: number | null;
  page_count: number | null;
  created_at?: string;
  ready_at?: string;
}

/** 上传响应，对应 API-2 */
export interface UploadDocumentResponse {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  deduplicated: boolean;
  created_at?: string;
}

export interface DocumentError {
  code: string;
  message: string;
}

/** 文档状态响应，对应 API-3 */
export interface DocumentStatusResponse {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  chunk_count: number | null;
  page_count: number | null;
  updated_at?: string;
  error: DocumentError | null;
}

/** 引用，对应 prd/05-api-spec.md §2.2 */
export interface Citation {
  document_id: string;
  chunk_id: string;
  filename: string;
  page: number | null;
  section: string | null;
  quote: string;
  score?: number;
}
