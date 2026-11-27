import { Button, Typography } from 'antd';
import { BookOpen } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';

const NAV_ITEMS = [
  { key: '/documents', label: '文档管理' },
  { key: '/chat', label: '智能问答' },
];

/** 顶部导航栏：fixed 定位，内容区需设置 pt-14 避免遮挡 */
export function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <header className="paper-topnav fixed inset-x-0 top-0 z-50 flex h-14 items-center justify-between px-6">
      <button
        type="button"
        className="flex cursor-pointer items-center gap-3 border-0 bg-transparent p-0"
        onClick={() => navigate('/documents')}
        aria-label="返回文档管理"
      >
        <span className="paper-brand-mark">
          <BookOpen size={17} strokeWidth={1.8} />
        </span>
        <span className="paper-brand flex items-baseline gap-2">
          <Typography.Text strong className="text-ink text-base">
            Alethix · 探赜
          </Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            Evidence-first reading
          </Typography.Text>
        </span>
      </button>

      <nav className="flex items-center gap-1" aria-label="主导航">
        {NAV_ITEMS.map((item) => {
          const active = location.pathname.startsWith(item.key);
          return (
            <Button
              key={item.key}
              type={active ? 'primary' : 'text'}
              className="paper-nav-button"
              onClick={() => navigate(item.key)}
            >
              {item.label}
            </Button>
          );
        })}
      </nav>
    </header>
  );
}
