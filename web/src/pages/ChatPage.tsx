import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Card, Drawer, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { PanelLeft, PanelRight } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { listDocuments } from '@/api/documents';
import { ChatComposer } from '@/components/chat/ChatComposer';
import { ChatMessageList } from '@/components/chat/ChatMessageList';
import { ResearchChain } from '@/components/chat/ResearchChain';
import { SessionRail } from '@/components/session/SessionRail';
import { useAskStream } from '@/hooks/useAskStream';
import { useSessionMessages } from '@/hooks/useSession';
import { useAppStore } from '@/store/useAppStore';
import type { FinalAnswerEvent } from '@/types/sse';
import { toBubbleItems, toResearchChainItems } from '@/utils/chatAdapters';

/** Ant Design X 问答调研页：会话侧栏 + 对话区 + 可收起的调研过程。 */
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
  const [researchOpen, setResearchOpen] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const lastSessionRef = useRef<string | null | undefined>(undefined);
  const activeSessionRef = useRef(activeSessionId);
  const turnRef = useRef(0);

  const history = useSessionMessages(activeSessionId);
  const historyRef = useRef(history);
  const timelineState = useAskStream();
  const { start, stop, settle, reset } = timelineState;

  const documentNames = useQuery({
    queryKey: ['documents', 'scope-names'],
    queryFn: () => listDocuments({ page: 1, page_size: 100 }),
    staleTime: 60_000,
  });
  const nameById = useMemo(
    () => new Map(documentNames.data?.items.map((doc) => [doc.document_id, doc.filename]) ?? []),
    [documentNames.data],
  );

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

  const research = <ResearchChain items={chainItems} />;
  const scopeTags = scopeIds.length ? (
    scopeIds.map((id) => (
      <Tag
        key={id}
        closable
        className="paper-scope-tag"
        onClose={() => setExcluded({ sessionId: activeSessionId, ids: [...excludedDocIds, id] })}
      >
        {nameById.get(id) ?? `${id.slice(0, 8)}…`}
      </Tag>
    ))
  ) : (
    <Tag className="paper-scope-tag">全部就绪文档</Tag>
  );

  return (
    <div className="mx-auto flex h-[calc(100vh-104px)] min-h-[620px] w-full max-w-[1440px] flex-col gap-4">
      <div className="paper-hero flex shrink-0 items-start justify-between gap-4 px-6 py-4">
        <div>
          <Typography.Title level={4} className="paper-title mb-1">
            智能问答 · 调研工作台
          </Typography.Title>
          <Typography.Text className="paper-hero-subtitle text-sm">
            每一轮检索、证据判断与引用均可逐步核对，答案不会脱离原文依据
          </Typography.Text>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            icon={<PanelLeft size={16} />}
            className="paper-research-toggle xl:hidden"
            onClick={() => setSessionOpen(true)}
          >
            会话
          </Button>
          <Button
            icon={<PanelRight size={16} />}
            className="paper-research-toggle xl:hidden"
            onClick={() => setResearchOpen(true)}
          >
            调研过程
          </Button>
        </div>
      </div>

      {!activeSessionId && (
        <Alert
          type="info"
          showIcon
          message="尚未选择会话"
          description="请先在文档管理页选择文档并发起提问，系统会为本次调研创建会话。"
        />
      )}

      <div className="flex min-h-0 flex-1 gap-4">
        <SessionRail session={session} className="hidden xl:flex" />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <Card
            title="检索范围"
            className="paper-scope-card border-paper-line shrink-0 shadow-sm"
            styles={{ body: { padding: 12 } }}
          >
            <div className="flex flex-wrap items-center gap-2">
              {scopeTags}
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

          <div className="paper-chat-panel flex min-h-0 flex-1 flex-col overflow-hidden border">
            {history.isError && (
              <Alert
                type="warning"
                showIcon
                title="会话历史加载失败"
                description={
                  history.olderError ?? '当前答案与调研过程仍可查看，稍后可刷新页面重试。'
                }
              />
            )}
            {history.hasOlder && (
              <div className="border-paper-line shrink-0 border-b px-4 py-2">
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
            <div className="border-paper-line shrink-0 border-t p-4">
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
        </div>

        <Card
          title="调研过程"
          className="paper-research-card hidden shrink-0 overflow-auto xl:block"
          styles={{ body: { padding: 16 } }}
        >
          {research}
        </Card>
      </div>

      <Drawer
        title="调研过程"
        placement="right"
        width={400}
        open={researchOpen}
        onClose={() => setResearchOpen(false)}
        className="paper-drawer"
      >
        {research}
      </Drawer>
      <Drawer
        title="会话信息"
        placement="left"
        width={320}
        open={sessionOpen}
        onClose={() => setSessionOpen(false)}
        className="paper-drawer"
      >
        <SessionRail session={session} className="border-0 bg-transparent shadow-none" />
      </Drawer>
    </div>
  );
}
