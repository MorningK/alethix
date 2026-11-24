import { Alert, Button } from 'antd';

interface ErrorAlertProps {
  message: string | null;
  onClose: () => void;
  onRetry?: () => void;
}

export function ErrorAlert({ message, onClose, onRetry }: ErrorAlertProps) {
  if (!message) return null;
  return (
    <Alert
      type="error"
      showIcon
      message={message}
      action={
        <div className="flex items-center gap-1">
          {onRetry && (
            <Button type="link" size="small" onClick={onRetry}>
              重试
            </Button>
          )}
          <Button type="text" size="small" onClick={onClose}>
            关闭
          </Button>
        </div>
      }
    />
  );
}
