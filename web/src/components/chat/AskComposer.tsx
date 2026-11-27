import { useState } from 'react';
import { Button, Card, Input, Typography } from 'antd';

interface AskComposerProps {
  running: boolean;
  disabled?: boolean;
  onSubmit: (question: string) => void;
  onStop: () => void;
}

/** 提问输入区：调研中禁用输入，并提供停止按钮（FE-CHAT-6）。 */
export function AskComposer({ running, disabled = false, onSubmit, onStop }: AskComposerProps) {
  const [value, setValue] = useState('');
  const blocked = running || disabled;

  const submit = () => {
    const question = value.trim();
    if (!question || blocked) return;
    onSubmit(question);
    setValue('');
  };

  return (
    <Card className="border-slate-100 shadow-sm" styles={{ body: { padding: 20 } }}>
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <Typography.Text className="text-ink text-base font-medium">提出调研问题</Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            支持追问，例如「那它的缺点呢？」
          </Typography.Text>
        </div>
        <Input.TextArea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          autoSize={{ minRows: 3, maxRows: 8 }}
          maxLength={2000}
          disabled={blocked}
          showCount
          placeholder="例如：结合所选文档，说明项目面临的主要合规风险及依据"
          className="resize-none"
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Typography.Text type="secondary" className="text-xs">
            Enter 提交 · Shift + Enter 换行 · 单次最多 2000 字
          </Typography.Text>
          <div className="flex items-center gap-2">
            {running && (
              <Button danger onClick={onStop}>
                停止调研
              </Button>
            )}
            <Button
              type="primary"
              loading={running}
              disabled={blocked || !value.trim()}
              onClick={submit}
            >
              发起调研
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
