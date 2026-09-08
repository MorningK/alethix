import { Button, Typography } from 'antd';
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
    <header className="fixed inset-x-0 top-0 z-50 flex h-14 items-center justify-between border-b border-black/5 bg-white px-6">
      <div className="flex items-center gap-2">
        <Typography.Text strong className="text-base">
          Alethix
        </Typography.Text>
        <Typography.Text type="secondary" className="text-sm">
          探赜
        </Typography.Text>
      </div>

      <nav className="flex items-center gap-1">
        {NAV_ITEMS.map((item) => {
          const active = location.pathname.startsWith(item.key);
          return (
            <Button
              key={item.key}
              type={active ? 'primary' : 'text'}
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
