import dayjs from 'dayjs';

export function formatFileSize(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatTime(value?: string): string {
  if (!value) return '-';
  return dayjs(value).format('YYYY-MM-DD HH:mm');
}

export function formatDuration(ms?: number): string {
  if (ms === undefined || ms === null) return '-';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
