import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from '@/components/layout/AppLayout';
import { ChatPage } from '@/pages/ChatPage';
import { DocumentsPage } from '@/pages/DocumentsPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

/** 路由表，见 prd/07-frontend.md §4.1 */
export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/documents" replace />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
