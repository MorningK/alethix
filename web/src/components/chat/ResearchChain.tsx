import { Alert, Typography } from 'antd';
import { ThoughtChain } from '@ant-design/x';
import type { ResearchChainItem } from '@/utils/chatAdapters';

interface ResearchChainProps {
  items: ResearchChainItem[];
}

/** 调研过程：把逐轮事件映射为可折叠的思维链节点。 */
export function ResearchChain({ items }: ResearchChainProps) {
  if (items.length === 0) {
    return (
      <Alert
        type="info"
        showIcon
        title="调研过程尚未开始"
        description="发起提问后，每一轮的查询、召回与判断会在这里逐步呈现。"
      />
    );
  }

  return (
    <div className="paper-research-chain flex flex-col gap-2">
      <Typography.Text type="secondary" className="text-xs">
        共 {items.length} 轮调研，展开节点可查看详细说明
      </Typography.Text>
      <ThoughtChain
        items={items}
        classNames={{ itemContent: 'research-chain-content' }}
        line="solid"
      />
    </div>
  );
}
