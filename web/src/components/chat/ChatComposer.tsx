import { Flex, Typography } from 'antd';
import { Prompts, Sender, Welcome } from '@ant-design/x';
import { RECOMMENDED_PROMPTS } from '@/utils/chatAdapters';

interface ChatComposerProps {
  value: string;
  running: boolean;
  disabled?: boolean;
  showPrompts: boolean;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  onCancel: () => void;
}

/** 输入区：Sender 承载提问与停止，Prompts 提供空会话引导。 */
export function ChatComposer({
  value,
  running,
  disabled = false,
  showPrompts,
  onChange,
  onSubmit,
  onCancel,
}: ChatComposerProps) {
  return (
    <Flex vertical gap={12}>
      {showPrompts && (
        <Flex vertical align="center" gap={12} className="py-10">
          <Welcome
            title="基于文档开始调研"
            description="输入问题后，系统会逐轮检索证据并给出可核验的结论；也可以从下方推荐问题开始。"
            variant="borderless"
          />
          <Prompts
            items={RECOMMENDED_PROMPTS.map((item) => ({
              key: item.key,
              label: item.label,
              description: item.description,
            }))}
            wrap
            onItemClick={({ data }) => onChange(String(data.description ?? ''))}
          />
          <Typography.Text type="secondary" className="text-xs">
            推荐问题点击后填入输入框，确认后即可发起调研
          </Typography.Text>
        </Flex>
      )}

      <Sender
        value={value}
        onChange={onChange}
        loading={running}
        disabled={disabled}
        submitType="enter"
        autoSize={{ minRows: 2, maxRows: 6 }}
        placeholder="例如：结合所选文档，说明项目面临的主要合规风险及依据"
        onSubmit={(message) => {
          const question = message.trim();
          if (question) onSubmit(question);
        }}
        onCancel={onCancel}
      />
    </Flex>
  );
}
