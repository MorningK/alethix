import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Tag, Typography } from 'antd';
import { useParams } from 'react-router-dom';
import { AnswerPanel } from '@/components/chat/AnswerPanel';
import { AskComposer } from '@/components/chat/AskComposer';
import { MessageHistory } from '@/components/chat/MessageHistory';
import { ResearchTimeline } from '@/components/chat/ResearchTimeline';
import { useAskStream } from '@/hooks/useAskStream';
import { useAppStore } from '@/store/useAppStore';

/** 问答调研页：F3 的时间线、答案引用、追问与停止交互。 */
export function ChatPage() {
  const { sessionId } = useParams();
  const queryClient = useQueryClient();
  const currentSessionId = useAppStore((state) => state.currentSessionId);
  const currentSession = useAppStore((state) => state.currentSession);
  const selectedDocIds = useAppStore((state) => state.selectedDocIds);
  const activeSessionId = sessionId ?? currentSessionId;
  const session = currentSession?.session_id === activeSessionId ? currentSession : null;
  const allScopeIds = session?.default_document_ids ?? selectedDocIds;
  const [excluded, setExcluded] = useState<{ sessionId: string | null; ids: string[] }>({
    sessionId: null,
    ids: [],
  });
  const lastSessionRef = useRef<string | null>(null);
  const { timeline, running, error, finalAnswer, start, stop } = useAskStream();

  useEffect(() => {
    if (lastSessionRef.current !== activeSessionId) {
      lastSessionRef.current = activeSessionId;
      stop();
    }
  }, [activeSessionId, stop]);

  const excludedDocIds = excluded.sessionId === activeSessionId ? excluded.ids : [];
  const scopeIds = allScopeIds.filter((id) => !excludedDocIds.includes(id));

  const handleFinal = useCallback(() => {
    if (activeSessionId) {
      queryClient.invalidateQueries({ queryKey: ['messages', activeSessionId] });
    }
  }, [activeSessionId, queryClient]);

  const handleSubmit = (question: string) => {
    if (!activeSessionId) return;
    start(
      {
        session_id: activeSessionId,
        question,
        document_ids: scopeIds,
        max_iterations: 3,
      },
      handleFinal,
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-5">
      <div className="rounded-xl bg-gradient-to-r from-[#1D4ED8] to-[#3B82F6] px-6 py-5 text-white shadow-sm">
        <Typography.Title level={3} className="mb-1 text-white">
          智能问答 · 调研工作台
        </Typography.Title>
        <Typography.Text className="text-white/80">
          每一轮检索、证据判断与引用均可逐步核对，答案不会脱离原文依据
        </Typography.Text>
      </div>

      {!activeSessionId && (
        <Alert
          type="info"
          showIcon
          message="尚未选择会话"
          description="请先在文档管理页选择文档并发起提问，系统会为本次调研创建会话。"
        />
      )}

      <Card
        title="检索范围"
        className="border-slate-100 shadow-sm"
        styles={{ body: { padding: 16 } }}
      >
        <div className="flex flex-wrap items-center gap-2">
          {scopeIds.length > 0 ? (
            scopeIds.map((id) => (
              <Tag
                key={id}
                closable
                onClose={() =>
                  setExcluded({ sessionId: activeSessionId, ids: [...excludedDocIds, id] })
                }
                color="blue"
              >
                {id.slice(0, 8)}…
              </Tag>
            ))
          ) : (
            <Tag color="blue">全部就绪文档</Tag>
          )}
          {excludedDocIds.length > 0 && (
            <Button
              type="link"
              size="small"
              onClick={() => setExcluded({ sessionId: activeSessionId, ids: [] })}
            >
              恢复全部范围
            </Button>
          )}
          {!session && activeSessionId && (
            <Typography.Text type="secondary" className="text-xs">
              当前浏览器未保存该会话的范围，默认检索全部就绪文档
            </Typography.Text>
          )}
        </div>
      </Card>

      <AskComposer
        running={running}
        disabled={!activeSessionId}
        onSubmit={handleSubmit}
        onStop={stop}
      />

      {error && <Alert type="error" showIcon message="调研未能完成" description={error} />}

      <div className="flex flex-col gap-5 xl:flex-row">
        <div className="xl:w-[320px] xl:shrink-0">
          <MessageHistory sessionId={activeSessionId} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <Card
            title="调研时间线"
            className="border-slate-100 shadow-sm"
            styles={{ body: { padding: 16 } }}
          >
            <ResearchTimeline nodes={timeline} running={running} />
          </Card>
          {finalAnswer && <AnswerPanel answer={finalAnswer} />}
        </div>
      </div>
    </div>
  );
}
