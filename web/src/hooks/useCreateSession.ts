import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { createSession } from '@/api/sessions';
import { useAppStore } from '@/store/useAppStore';

/** 新建会话：复用既有 createSession 接口，并同步轻量 UI store。 */
export function useCreateSession() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setCurrentSession = useAppStore((state) => state.setCurrentSession);

  return useMutation({
    mutationFn: () => createSession({ title: '新调研会话' }),
    onSuccess: (session) => {
      setCurrentSession(session);
      queryClient.invalidateQueries({ queryKey: ['messages', session.session_id] });
      navigate(`/chat/${session.session_id}`);
    },
    onError: (error) => console.error('[session] 创建会话失败', error),
  });
}
