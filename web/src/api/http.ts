import axios, { AxiosError } from 'axios';

/** 统一错误对象，由拦截器解析后端 { error: { code, message, trace_id } } 得到 */
export class ApiError extends Error {
  code: string;
  status: number;
  traceId?: string;
  details?: Record<string, unknown>;

  constructor(params: {
    message: string;
    code: string;
    status: number;
    traceId?: string;
    details?: Record<string, unknown>;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.code = params.code;
    this.status = params.status;
    this.traceId = params.traceId;
    this.details = params.details;
  }
}

const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/** 开发期模拟用户标识；生产由网关注入 X-User-Id，前端不感知鉴权 */
const devUserId = import.meta.env.VITE_USER_ID ?? '';

export const http = axios.create({
  baseURL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.request.use((config) => {
  if (devUserId) {
    config.headers['X-User-Id'] = devUserId;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (
    error: AxiosError<{
      error?: {
        code: string;
        message: string;
        trace_id?: string;
        details?: Record<string, unknown>;
      };
    }>,
  ) => {
    const payload = error.response?.data?.error;
    const apiError = new ApiError({
      message: payload?.message ?? error.message ?? '请求失败',
      code: payload?.code ?? 'UNKNOWN',
      status: error.response?.status ?? 0,
      traceId: payload?.trace_id,
      details: payload?.details,
    });
    console.error('[api]', apiError.code, apiError.message, apiError.traceId ?? '');
    return Promise.reject(apiError);
  },
);
