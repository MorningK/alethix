import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { XProvider } from '@ant-design/x';
import zhCN_X from '@ant-design/x/locale/zh_CN';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { paperTheme } from './theme/paperTheme';
import './index.css';
import './styles/paper-theme.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

const container = document.getElementById('root');
if (!container) {
  throw new Error('未找到 #root 挂载点');
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={paperTheme}>
        <XProvider locale={{ ...zhCN, ...zhCN_X }}>
          <AntdApp>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </AntdApp>
        </XProvider>
      </ConfigProvider>
    </QueryClientProvider>
  </StrictMode>,
);
