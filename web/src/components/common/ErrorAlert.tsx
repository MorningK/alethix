import { Alert, Button } from 'antd';

interface ErrorAlertProps {
  message: string | null;
  onClose: () => void;
}

export function ErrorAlert({ message, onClose }: ErrorAlertProps) {
  if (!message) return null;
  return (
    <Alert
      type="error"
      showIcon
      message={message}
      action={
        <Button type="text" size="small" onClick={onClose}>
          关闭
        </Button>
      }
    />
  );
}
