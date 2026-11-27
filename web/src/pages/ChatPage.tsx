import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Card, Tag, Typography } from 'antd';
import { useParams } from 'react-router-dom';
import { ChatComposer } from '@/components/chat/ChatComposer';
import { ChatMessageList } from '@/components/chat/ChatMessageList';
import { ResearchChain } from '@/components/chat/ResearchChain';
import { useAskStream } from '@/hooks/useAskStream';
import { useSessionMessages } from '@/hooks/useSession';
import { useAppStore } from '@/store/useAppStore';
import type { FinalAnswerEvent } from '@/types/sse';
import { toBubbleItems, toResearchChainItems } from '@/utils/chatAdapters';

/** Ant Design X 问答调研页：对话气泡 + 调研思维链 + Sender。 */
export function ChatPage() {
  const { sessionId } = useParams();
  const currentSessionId = useAppStore((state) => state.currentSessionId);
  const currentSession = useAppStore((state) => state.currentSession);
  const selectedDocIds = useAppStore((state) => state.selectedDocIds);
  const activeSessionId = sessionId ?? currentSessionId;
  const session = currentSession?.session_id === activeSessionId ? currentSession : null;
  const allScopeIds = session?.default_document_ids ?? selectedDocIds;

  const [value, setValue] = useState('');
  const [excluded, setExcluded] = useState<{ sessionId: string | null; ids: string[] }>({
    sessionId: null,
    ids: [],
  });
  const lastSessionRef = useRef<string | null | undefined>(undefined);
  const activeSessionRef = useRef(activeSessionId);
  const turnRef = useRef(0);

  const history = useSessionMessages(activeSessionId);
  const historyRef = useRef(history);
  const timelineState = useAskStream();
  const { start, stop, settle, reset } = timelineState;

  useEffect(() => {
    historyRef.current = history;
  }, [history]);

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
    const previousSessionId = lastSessionRef.current;
    lastSessionRef.current = activeSessionId;
    if (previousSessionId !== undefined && previousSessionId !== activeSessionId) {
      reset();
    }
  }, [activeSessionId, reset]);

  const excludedDocIds = excluded.sessionId === activeSessionId ? excluded.ids : [];
  const scopeIds = allScopeIds.filter((id) => !excludedDocIds.includes(id));

  const handleFinal = useCallback(
    async (event: FinalAnswerEvent, turn: number) => {
      if (activeSessionRef.current !== activeSessionId || turnRef.current !== turn) return;
      try {
        const refreshed = await historyRef.current.refetchHistory();
        const persisted = refreshed.items.some(
          (item) => item.role === 'assistant' && item.agent_run_id === event.agent_run_id,
        );
        if (persisted && activeSessionRef.current === activeSessionId && turnRef.current === turn) {
          settle();
        }
      } catch (error) {
        console.error('[chat] 历史刷新失败，保留当前答案', error);
      }
    },
    [activeSessionId, settle],
  );

  const handleSubmit = (question: string) => {
    if (!activeSessionId) return;
    setValue('');
    turnRef.current += 1;
    const turn = turnRef.current;
    start(
      {
        session_id: activeSessionId,
        question,
        document_ids: scopeIds,
        max_iterations: 3,
      },
      (event) => handleFinal(event, turn),
    );
  };

  const bubbleItems = useMemo(
    () =>
      toBubbleItems({
        history: history.items,
        currentQuestion: timelineState.currentQuestion,
        running: timelineState.running,
        finalAnswer: timelineState.finalAnswer,
        error: timelineState.error,
        aborted: timelineState.aborted,
      }),
    [
      history.items,
      timelineState.currentQuestion,
      timelineState.running,
      timelineState.finalAnswer,
      timelineState.error,
      timelineState.aborted,
    ],
  );

  const chainItems = useMemo(
    () => toResearchChainItems(timelineState.timeline, timelineState.finalAnswer),
    [timelineState.timeline, timelineState.finalAnswer],
  );

  return (
    <div className="mx-auto flex h-[calc(100vh-104px)] min-h-[620px] w-full max-w-7xl flex-col gap-4">
      <div className="shrink-0 rounded-xl bg-gradient-to-r from-[#1D4ED8] to-[#3B82F6] px-6 py-4 text-white shadow-sm">
        <Typography.Title level={4} className="mb-1 text-white">
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
        className="shrink-0 border-slate-100 shadow-sm"
        styles={{ body: { padding: 12 } }}
      >
        <div className="flex flex-wrap items-center gap-2">
          {scopeIds.length > 0 ? (
            scopeIds.map((id) => (
              <Tag
                key={id}
                closable
                color="blue"
                onClose={() =>
                  setExcluded({ sessionId: activeSessionId, ids: [...excludedDocIds, id] })
                }
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

      {timelineState.error && (
        <Alert type="error" showIcon title="调研未能完成" description={timelineState.error} />
      )}
      {timelineState.aborted && !timelineState.error && (
        <Alert
          type="warning"
          showIcon
          title="调研已停止"
          description="本次未生成完整答案，可重新提问继续调研。"
        />
      )}

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-100 bg-white shadow-sm">
          {history.isError && (
            <Alert
              type="warning"
              showIcon
              title="会话历史加载失败"
              description={history.olderError ?? '当前答案与调研过程仍可查看，稍后可刷新页面重试。'}
            />
          )}
          {history.hasOlder && (
            <div className="shrink-0 border-b border-slate-100 px-4 py-2">
              <Button
                type="link"
                size="small"
                loading={history.loadingOlder}
                onClick={history.loadOlder}
              >
                加载更早消息
              </Button>
            </div>
          )}
          <div className="min-h-0 flex-1">
            <ChatMessageList items={bubbleItems} />
          </div>
          <div className="shrink-0 border-t border-slate-100 p-4">
            <ChatComposer
              value={value}
              running={timelineState.running}
              disabled={!activeSessionId}
              showPrompts={bubbleItems.length === 0 && !timelineState.running}
              onChange={setValue}
              onSubmit={handleSubmit}
              onCancel={stop}
            />
          </div>
        </div>

        <Card
          title="调研过程"
          className="hidden w-[340px] shrink-0 overflow-auto border-slate-100 shadow-sm xl:block"
          styles={{ body: { padding: 16 } }}
        >
          <ResearchChain items={chainItems} />
        </Card>
      </div>
    </div>
  );
}
